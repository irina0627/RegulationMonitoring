"""그래프 빌더 테스트 (실제 PostgreSQL).

엔터티 정규화 upsert + 엣지 중복 없는 연결을 검증한다.
그래프 테이블은 이 개발 DB 에서 테스트 전용이므로 전체 초기화한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.graph import builder
from app.models.entity import Entity as EntityModel
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource


@pytest.fixture()
def session_and_issue():
    with SessionLocal() as s:
        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(EntityModel))
        issue = Issue(title="테스트 이슈")
        s.add(issue)
        s.flush()
        yield s, issue.id
        s.rollback()


def test_upsert_entity_normalizes_registered(session_and_issue) -> None:
    s, _ = session_and_issue
    eid, registered = builder.upsert_entity(s, "regulation", "자본시장법")
    assert registered is True
    row = s.get(EntityModel, eid)
    assert row.canonical_name == "자본시장과 금융투자업에 관한 법률"
    assert row.meta is None  # 등록 엔터티는 플래그 없음


def test_upsert_entity_flags_unregistered(session_and_issue) -> None:
    s, _ = session_and_issue
    eid, registered = builder.upsert_entity(s, "sector", "서민금융")
    assert registered is False
    row = s.get(EntityModel, eid)
    assert row.canonical_name == "서민금융"  # 원시명 유지
    assert row.meta == {"unregistered": True}


def test_upsert_entity_dedup_by_canonical(session_and_issue) -> None:
    s, _ = session_and_issue
    # 약칭과 정식명은 같은 canonical → 같은 행
    id1, _ = builder.upsert_entity(s, "regulation", "자본시장법")
    id2, _ = builder.upsert_entity(s, "regulation", "자본시장과 금융투자업에 관한 법률")
    assert id1 == id2
    rows = s.execute(
        select(EntityModel).where(EntityModel.type == "regulation")
    ).scalars().all()
    assert len(rows) == 1


def test_upsert_entity_stores_enforce_date(session_and_issue) -> None:
    s, _ = session_and_issue
    eid, _ = builder.upsert_entity(
        s, "regulation", "가상자산이용자보호법", enforce_date="2024-07-19"
    )
    row = s.get(EntityModel, eid)
    assert row.meta["enforce_date"] == "2024-07-19"


def test_link_issue_entity_is_idempotent(session_and_issue) -> None:
    s, issue_id = session_and_issue
    eid, _ = builder.upsert_entity(s, "sector", "증권")

    assert builder.link_issue_entity(s, issue_id, eid, "affects") is True
    assert builder.link_issue_entity(s, issue_id, eid, "affects") is False  # 중복
    s.flush()
    rows = s.execute(
        select(IssueEntity).where(IssueEntity.issue_id == issue_id)
    ).scalars().all()
    assert len(rows) == 1


def test_link_issue_source_is_idempotent(session_and_issue) -> None:
    s, issue_id = session_and_issue
    assert builder.link_issue_source(s, issue_id, "press_release", 999, "trigger") is True
    assert builder.link_issue_source(s, issue_id, "press_release", 999, "trigger") is False
    s.flush()
    rows = s.execute(
        select(IssueSource).where(IssueSource.issue_id == issue_id)
    ).scalars().all()
    assert len(rows) == 1


def test_relation_for() -> None:
    assert builder.relation_for("regulation") == "based_on"
    assert builder.relation_for("sector") == "affects"
    assert builder.relation_for("dept") == "handled_by"
    assert builder.relation_for("unknown") == "affects"
