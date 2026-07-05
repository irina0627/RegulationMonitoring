"""지식 그래프 빌더 (설계서 6장).

이슈-엔터티(issue_entity)·이슈-소스(issue_source) 엣지를 정합성 있게 구축·갱신한다.
- 엔터티는 시드 온톨로지로 정규화(nlp.entity) 후 (type, canonical_name) 기준 upsert.
- 엣지는 중복 없이 연결(idempotent). 표출용 시각화는 만들지 않는다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.entity import Entity as EntityModel
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.nlp.entity import normalize_entity

log = get_logger(__name__)

# 엔터티 타입 → 이슈-엔터티 관계 (설계서 6.2)
RELATION_BY_TYPE = {
    "regulation": "based_on",
    "sector": "affects",
    "product": "affects",
    "agency": "handled_by",
    "dept": "handled_by",
}


def relation_for(etype: str) -> str:
    return RELATION_BY_TYPE.get((etype or "").lower(), "affects")


def upsert_entity(
    session: Session,
    etype: str,
    name: str,
    *,
    enforce_date: str | None = None,
    llm_canonical: str | None = None,
) -> tuple[int, bool]:
    """엔터티를 정규화 후 (type, canonical_name) 기준 upsert. (entity_id, registered) 반환.

    - 온톨로지 등록 명칭이면 표준 canonical 사용.
    - 미등록이면 LLM canonical 또는 원시명 유지 + metadata.unregistered=True 플래그.
    """
    norm = normalize_entity(etype, name)
    if norm.registered:
        canonical = norm.canonical_name
    else:
        canonical = (llm_canonical or norm.canonical_name or name).strip()

    meta: dict = {}
    if enforce_date:
        meta["enforce_date"] = enforce_date
    if not norm.registered:
        meta["unregistered"] = True

    stmt = pg_insert(EntityModel).values(
        type=norm.type, name=name.strip(), canonical_name=canonical, meta=meta or None
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["type", "canonical_name"],  # uq_entity_type_canonical
        set_={"name": stmt.excluded.name},
    ).returning(EntityModel.id)
    entity_id = session.execute(stmt).scalar_one()
    return entity_id, norm.registered


def link_issue_entity(
    session: Session, issue_id: int, entity_id: int, relation: str
) -> bool:
    """issue_entity 엣지를 중복 없이 연결. 새로 추가되면 True."""
    exists = session.execute(
        select(IssueEntity.id).where(
            IssueEntity.issue_id == issue_id,
            IssueEntity.entity_id == entity_id,
            IssueEntity.relation == relation,
        )
    ).first()
    if exists:
        return False
    session.add(
        IssueEntity(issue_id=issue_id, entity_id=entity_id, relation=relation)
    )
    session.flush()  # 이후 중복 검사가 이 엣지를 보게 함
    return True


def link_issue_source(
    session: Session,
    issue_id: int,
    source_type: str,
    source_id: int,
    relation: str,
) -> bool:
    """issue_source 엣지를 중복 없이 연결. 새로 추가되면 True."""
    exists = session.execute(
        select(IssueSource.id).where(
            IssueSource.issue_id == issue_id,
            IssueSource.source_type == source_type,
            IssueSource.source_id == source_id,
            IssueSource.relation == relation,
        )
    ).first()
    if exists:
        return False
    session.add(
        IssueSource(
            issue_id=issue_id,
            source_type=source_type,
            source_id=source_id,
            relation=relation,
        )
    )
    session.flush()  # 이후 중복 검사가 이 엣지를 보게 함
    return True
