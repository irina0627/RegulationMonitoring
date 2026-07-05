"""Enrich 파이프라인 테스트 (LLM mock, 실제 PostgreSQL).

이슈·엔터티·엣지 적재와 멱등성을 검증한다.
test-enrich-* guid 로 격리·정리한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, update

from app.core.db import SessionLocal
from app.models.entity import Entity as EntityModel
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.models.press_release import PressRelease
from app.nlp import enrich as enrich_mod
from app.nlp.enrich import run_enrich
from app.nlp.llm_client import Entity, Impact, Summary

GUID = "test-enrich-001"
BODY = "자본시장법 개정으로 ELS 판매 규제가 강화된다. 금융위 의결을 거쳤다."

# 이 테스트에서 만들어지는 엔터티 정규화명 (정리용)
_TEST_CANONICALS = {
    "자본시장과 금융투자업에 관한 법률",
    "자본시장과",
    "증권",
    "ELS",
}


class FakeLLM:
    """LLMClient 인터페이스를 만족하는 결정적 mock."""

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, text: str) -> Summary:
        self.calls += 1
        return Summary(summary="ELS 판매규제 강화", why_it_matters="증권 상품 컴플라이언스 영향")

    def extract_entities(self, text: str) -> list[Entity]:
        self.calls += 1
        return [
            Entity("regulation", "자본시장법", "자본시장과 금융투자업에 관한 법률", "2026-01-01"),
            Entity("dept", "자본시장과", None),
            Entity("sector", "증권", None),
        ]

    def classify_lifecycle(self, text: str) -> str:
        self.calls += 1
        return "DECISION"

    def assess_impact(self, text: str) -> Impact:
        self.calls += 1
        return Impact(sectors=["증권"], products=["ELS"], rationale="ELS 규제 강화")


def _purge() -> None:
    # 그래프 테이블(issue/entity/엣지)은 이 개발 DB 에서 테스트 전용이므로 전체 초기화.
    # (FK 순서: 엣지 → issue/entity). press_release 는 test 접두사만 제거.
    with SessionLocal() as s:
        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(EntityModel))
        s.execute(delete(PressRelease).where(PressRelease.rss_guid.like("test-enrich-%")))
        s.commit()


@pytest.fixture(autouse=True)
def _clean():
    enrich_mod.reset_cache()
    _purge()
    with SessionLocal() as s:
        # 테스트 격리: 기존(비-테스트) 보도자료는 done 처리해 run_enrich 대상에서 제외
        s.execute(
            update(PressRelease)
            .where(~PressRelease.rss_guid.like("test-enrich-%"))
            .values(enrich_status="done")
        )
        # pending 보도자료 1건 시드
        s.add(PressRelease(rss_guid=GUID, title="자본시장법 개정", body_text=BODY,
                           enrich_status="pending"))
        s.commit()
    yield
    _purge()


def _issue_for_guid():
    with SessionLocal() as s:
        pr_id = s.execute(
            select(PressRelease.id).where(PressRelease.rss_guid == GUID)
        ).scalar_one()
        iid = s.execute(
            select(IssueSource.issue_id).where(
                IssueSource.source_type == "press_release",
                IssueSource.source_id == pr_id,
                IssueSource.relation == "trigger",
            )
        ).scalar_one_or_none()
        return iid


def test_enrich_creates_issue_entities_edges() -> None:
    fake = FakeLLM()
    stats = run_enrich(client=fake, use_cache=False)

    assert stats["issues_created"] == 1
    assert fake.calls == 4  # 4종 LLM 호출

    iid = _issue_for_guid()
    assert iid is not None

    with SessionLocal() as s:
        issue = s.get(Issue, iid)
        assert issue.summary == "ELS 판매규제 강화"
        assert issue.lifecycle_stage == "DECISION"
        assert float(issue.importance_score) > 0

        # 엣지: based_on(법령), handled_by(부서), affects(증권, ELS)
        edges = s.execute(
            select(IssueEntity).where(IssueEntity.issue_id == iid)
        ).scalars().all()
        rels = sorted(e.relation for e in edges)
        assert rels == ["affects", "affects", "based_on", "handled_by"]

        # trigger 소스 엣지
        src = s.execute(
            select(IssueSource).where(IssueSource.issue_id == iid)
        ).scalars().all()
        assert len(src) == 1 and src[0].relation == "trigger"

        # 보도자료는 done
        pr = s.execute(
            select(PressRelease).where(PressRelease.rss_guid == GUID)
        ).scalar_one()
        assert pr.enrich_status == "done"


def test_enrich_is_idempotent() -> None:
    fake = FakeLLM()
    run_enrich(client=fake, use_cache=False)
    iid1 = _issue_for_guid()

    # 재실행: pending 없음 → 이슈 증가 없음
    stats2 = run_enrich(client=fake, use_cache=False)
    assert stats2["pending"] == 0
    assert stats2["issues_created"] == 0
    assert _issue_for_guid() == iid1


def test_enrich_idempotent_even_if_status_reset() -> None:
    fake = FakeLLM()
    run_enrich(client=fake, use_cache=False)
    iid1 = _issue_for_guid()

    # enrich_status 를 pending 으로 되돌려도, 기존 이슈가 있으면 새로 안 만든다
    with SessionLocal() as s:
        s.execute(
            PressRelease.__table__.update()
            .where(PressRelease.rss_guid == GUID)
            .values(enrich_status="pending")
        )
        s.commit()

    stats = run_enrich(client=fake, use_cache=False)
    assert stats["skipped_existing"] == 1
    assert stats["issues_created"] == 0
    assert _issue_for_guid() == iid1  # 동일 이슈 유지


def test_entity_dedup_across_two_press_releases() -> None:
    # 같은 엔터티를 참조하는 보도자료 2건 → 엔터티는 UNIQUE 로 1개만
    with SessionLocal() as s:
        s.add(PressRelease(rss_guid="test-enrich-002", title="추가", body_text=BODY,
                           enrich_status="pending"))
        s.commit()

    run_enrich(client=FakeLLM(), use_cache=False)

    with SessionLocal() as s:
        rows = s.execute(
            select(EntityModel).where(EntityModel.canonical_name == "증권")
        ).scalars().all()
        assert len(rows) == 1  # 중복 엔터티 없음


def test_cache_avoids_duplicate_llm_calls() -> None:
    # 같은 본문 2건 → 캐시로 두 번째는 LLM 재호출 안 함
    enrich_mod.reset_cache()
    with SessionLocal() as s:
        s.add(PressRelease(rss_guid="test-enrich-003", title="추가2", body_text=BODY,
                           enrich_status="pending"))
        s.commit()

    fake = FakeLLM()
    stats = run_enrich(client=fake, use_cache=True)
    assert stats["issues_created"] == 2
    assert fake.calls == 4  # 첫 본문만 4회, 두 번째는 캐시
    assert stats["cache_hits"] == 1
