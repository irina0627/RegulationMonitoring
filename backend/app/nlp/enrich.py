"""Enrich 파이프라인: press_release 본문 → LLM 4종 → issue/entity/edge 적재 (M2).

흐름(설계서 5.1 4~5단계):
  enrich_status='pending' 보도자료 선택
  → summarize / extract_entities / classify_lifecycle / assess_impact
  → issue 생성(요약·why·stage·importance)
  → entity 정규화 upsert(UNIQUE(type,canonical_name))
  → issue_entity 엣지(based_on/affects/handled_by) + issue_source 엣지(trigger)
  → enrich_status='done'

멱등성(CLAUDE.md 원칙 3):
  - enrich_status='pending' 만 처리 → done 은 재처리 안 함.
  - 추가 방어: 해당 press_release 를 trigger 하는 issue_source 가 이미 있으면 이슈를 새로 만들지 않음.
비용 통제(설계서 12.3): 같은 본문 재호출 방지 캐시.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.graph import builder
from app.models.issue import Issue
from app.models.issue_source import IssueSource
from app.models.press_release import PressRelease
from app.nlp import get_llm_client
from app.nlp.llm_client import Entity, Impact, LLMClient

log = get_logger(__name__)

# --- 라이프사이클 단계별 중요도 가중 (설계서 6.3) --------------------------- #
_STAGE_WEIGHT = {
    "PRE_NOTICE": 1.0,
    "DECISION": 2.0,
    "PROMULGATION": 2.0,
    "SUB_LAW": 3.0,
    "ENFORCEMENT": 4.0,
    "FOLLOW_UP": 2.0,
    "": 1.0,
}

# 같은 본문 재호출 방지 캐시 (body 해시 → EnrichResult)
_body_cache: dict[str, "EnrichResult"] = {}


@dataclass
class EnrichResult:
    summary: str
    why_it_matters: str
    lifecycle_stage: str
    entities: list[Entity] = field(default_factory=list)
    impact: Impact = field(default_factory=Impact)


def reset_cache() -> None:
    """본문 캐시 초기화(테스트/운영 재처리용)."""
    _body_cache.clear()


def compute_importance(stage: str, impact: Impact) -> float:
    """1차 중요도 점수 = 단계 가중 + 영향 폭. (정교한 스코어링은 이후 Score 단계)"""
    breadth = min(len(impact.sectors) + len(impact.products), 6) * 0.5
    return round(_STAGE_WEIGHT.get(stage, 1.0) + breadth, 2)


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _enrich_body(
    client: LLMClient, body: str, stats: dict, *, use_cache: bool
) -> EnrichResult:
    """본문에 4종 LLM 을 적용해 결과를 만든다. 캐시 적중 시 LLM 호출 생략."""
    key = _body_hash(body)
    if use_cache and key in _body_cache:
        stats["cache_hits"] += 1
        return _body_cache[key]

    sm = client.summarize(body)
    entities = client.extract_entities(body)
    stage = client.classify_lifecycle(body)
    impact = client.assess_impact(body)
    stats["llm_calls"] += 4

    result = EnrichResult(
        summary=sm.summary,
        why_it_matters=sm.why_it_matters,
        lifecycle_stage=stage,
        entities=entities,
        impact=impact,
    )
    if use_cache:
        _body_cache[key] = result
    return result


def _link_entities(session: Session, issue_id: int, res: EnrichResult) -> tuple[int, int]:
    """엔터티 정규화 upsert(builder) + issue_entity 엣지 연결. (엔터티수, 엣지수) 반환."""
    # (type, name, enforce_date, llm_canonical) 스펙 취합
    specs: list[tuple[str, str, str | None, str | None]] = []
    for e in res.entities:
        specs.append((e.type, e.name, e.enforce_date, e.canonical_name))
    for s in res.impact.sectors:
        specs.append(("sector", s, None, None))
    for p in res.impact.products:
        specs.append(("product", p, None, None))

    entity_ids: set[int] = set()
    linked: set[tuple[int, str]] = set()  # 같은 run 내 중복 엣지 방지
    for etype, name, enforce, llm_canonical in specs:
        if not name or not name.strip():
            continue
        entity_id, _registered = builder.upsert_entity(
            session, etype, name, enforce_date=enforce, llm_canonical=llm_canonical
        )
        entity_ids.add(entity_id)
        relation = builder.relation_for(etype)
        key = (entity_id, relation)
        if key in linked:
            continue
        if builder.link_issue_entity(session, issue_id, entity_id, relation):
            linked.add(key)
    return len(entity_ids), len(linked)


def run_enrich(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    client: LLMClient | None = None,
    limit: int | None = None,
    use_cache: bool = True,
) -> dict:
    """pending 보도자료를 이슈로 변환·적재한다. 통계 반환."""
    client = client or get_llm_client()
    stats = {
        "pending": 0,
        "issues_created": 0,
        "entities_upserted": 0,
        "edges": 0,
        "skipped_no_body": 0,
        "skipped_existing": 0,
        "llm_calls": 0,
        "cache_hits": 0,
    }

    with session_factory() as session:
        q = select(PressRelease).where(PressRelease.enrich_status == "pending")
        if limit:
            q = q.limit(limit)
        prs = session.execute(q).scalars().all()
        stats["pending"] = len(prs)

        for pr in prs:
            # 멱등 방어: 이미 이 보도자료로 만든 이슈가 있으면 건너뜀
            exists = session.execute(
                select(IssueSource.id).where(
                    IssueSource.source_type == "press_release",
                    IssueSource.source_id == pr.id,
                    IssueSource.relation == "trigger",
                )
            ).first()
            if exists:
                pr.enrich_status = "done"
                stats["skipped_existing"] += 1
                continue

            body = pr.body_text
            if not body or not body.strip():
                pr.enrich_status = "done"
                stats["skipped_no_body"] += 1
                continue

            res = _enrich_body(client, body, stats, use_cache=use_cache)

            issue = Issue(
                title=pr.title,
                summary=res.summary or None,
                why_it_matters=res.why_it_matters or None,
                lifecycle_stage=res.lifecycle_stage or None,
                importance_score=compute_importance(res.lifecycle_stage, res.impact),
            )
            session.add(issue)
            session.flush()  # issue.id 확보

            # 소스 엣지(trigger)
            builder.link_issue_source(
                session, issue.id, "press_release", pr.id, "trigger"
            )
            # 엔터티 + 엣지
            n_ent, n_edge = _link_entities(session, issue.id, res)
            stats["entities_upserted"] += n_ent
            stats["edges"] += n_edge

            pr.enrich_status = "done"
            stats["issues_created"] += 1

        session.commit()

    log.info(
        "Enrich 완료: 대상 %d건 → 이슈 %d건, 엔터티 %d, 엣지 %d "
        "(무본문 %d, 기존스킵 %d, LLM호출 %d, 캐시적중 %d)",
        stats["pending"], stats["issues_created"], stats["entities_upserted"],
        stats["edges"], stats["skipped_no_body"], stats["skipped_existing"],
        stats["llm_calls"], stats["cache_hits"],
    )
    return stats


# --- 수동 트리거용 중복 실행 방지 ------------------------------------------ #
_enrich_lock = threading.Lock()


def run_enrich_guarded(**kwargs) -> dict | None:
    """enrich 1회 실행하되 이미 진행 중이면 None(busy)."""
    if not _enrich_lock.acquire(blocking=False):
        log.info("이전 enrich 진행 중 — 이번 실행 건너뜀(busy)")
        return None
    try:
        return run_enrich(**kwargs)
    except Exception:  # noqa: BLE001
        log.exception("enrich 실행 중 예외")
        return None
    finally:
        _enrich_lock.release()
