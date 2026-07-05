"""이슈 수동 병합/분리 (설계서 6.4 보정 기능).

자동 클러스터링 오류를 사람이 엔드포인트/CLI 로 바로잡는 최소 기능.
병합 시 소스·엔터티 엣지를 대상 이슈로 정합성 있게 이전하고 중복을 제거한다(멱등).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource

log = get_logger(__name__)


def merge_issues(session: Session, source_id: int, target_id: int) -> dict:
    """source 이슈를 target 이슈로 병합한다.

    source 의 issue_source/issue_entity 엣지를 target 으로 이전하되,
    target 에 이미 같은 엣지가 있으면 중복은 버린다. 병합 후 source 이슈는 삭제.

    멱등: source 가 이미 없으면(=이미 병합됨) 조용히 no-op 반환.
    """
    if source_id == target_id:
        raise ValueError("source 와 target 이 동일합니다.")

    target = session.get(Issue, target_id)
    if target is None:
        raise LookupError(f"target 이슈 {target_id} 없음")

    source = session.get(Issue, source_id)
    if source is None:
        # 이미 병합/삭제됨 → 멱등 no-op
        return {"merged": False, "reason": "source_not_found", "source_id": source_id}

    # --- 소스 엣지 이전 ---
    tgt_src_keys = {
        (r.source_type, r.source_id, r.relation)
        for r in session.execute(
            select(IssueSource).where(IssueSource.issue_id == target_id)
        ).scalars()
    }
    moved_src = dropped_src = 0
    for r in session.execute(
        select(IssueSource).where(IssueSource.issue_id == source_id)
    ).scalars():
        key = (r.source_type, r.source_id, r.relation)
        if key in tgt_src_keys:
            session.delete(r)
            dropped_src += 1
        else:
            r.issue_id = target_id
            tgt_src_keys.add(key)
            moved_src += 1

    # --- 엔터티 엣지 이전 ---
    tgt_ent_keys = {
        (r.entity_id, r.relation)
        for r in session.execute(
            select(IssueEntity).where(IssueEntity.issue_id == target_id)
        ).scalars()
    }
    moved_ent = dropped_ent = 0
    for r in session.execute(
        select(IssueEntity).where(IssueEntity.issue_id == source_id)
    ).scalars():
        key = (r.entity_id, r.relation)
        if key in tgt_ent_keys:
            session.delete(r)
            dropped_ent += 1
        else:
            r.issue_id = target_id
            tgt_ent_keys.add(key)
            moved_ent += 1

    target.last_updated_at = func.now()
    # 엣지 이전/삭제를 먼저 반영한 뒤 이슈 삭제(관계 미정의라 FK 순서를 수동 보장)
    session.flush()
    session.delete(source)
    session.flush()

    result = {
        "merged": True,
        "target_id": target_id,
        "source_id": source_id,
        "moved_sources": moved_src,
        "moved_entities": moved_ent,
        "dropped_dup_sources": dropped_src,
        "dropped_dup_entities": dropped_ent,
    }
    log.info("이슈 병합: %s → %s %s", source_id, target_id, result)
    return result


def split_issue(
    session: Session,
    issue_id: int,
    source_ids: list[int],
    *,
    new_title: str | None = None,
) -> dict:
    """이슈의 일부 소스(issue_source.id 목록)를 새 이슈로 분리한다.

    선택한 소스 엣지를 새 이슈로 이전하고, 엔터티 태깅은 새 이슈로 복사한다(양쪽 유지).
    """
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise LookupError(f"이슈 {issue_id} 없음")

    rows = session.execute(
        select(IssueSource).where(
            IssueSource.id.in_(source_ids), IssueSource.issue_id == issue_id
        )
    ).scalars().all()
    if not rows:
        raise ValueError("이동할 소스가 없습니다(잘못된 source_ids 또는 이미 이동됨).")

    # 이슈에 소스가 1개뿐이면 분리 의미 없음
    total_src = session.execute(
        select(func.count()).select_from(IssueSource).where(
            IssueSource.issue_id == issue_id
        )
    ).scalar_one()
    if len(rows) >= total_src:
        raise ValueError("모든 소스를 분리할 수 없습니다(원본이 비게 됨).")

    new_issue = Issue(
        title=new_title or f"{issue.title} (분리)",
        summary=issue.summary,
        why_it_matters=issue.why_it_matters,
        lifecycle_stage=issue.lifecycle_stage,
        importance_score=issue.importance_score,
    )
    session.add(new_issue)
    session.flush()

    for r in rows:
        r.issue_id = new_issue.id

    # 엔터티 태깅 복사(새 이슈도 태그를 갖도록). 원본은 유지.
    copied = 0
    for r in session.execute(
        select(IssueEntity).where(IssueEntity.issue_id == issue_id)
    ).scalars():
        session.add(
            IssueEntity(
                issue_id=new_issue.id, entity_id=r.entity_id, relation=r.relation
            )
        )
        copied += 1

    session.flush()
    result = {
        "new_issue_id": new_issue.id,
        "moved_sources": len(rows),
        "copied_entities": copied,
    }
    log.info("이슈 분리: %s → 신규 %s %s", issue_id, new_issue.id, result)
    return result
