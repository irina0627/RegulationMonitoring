"""이슈 병합/분리 테스트 (실제 PostgreSQL).

병합 후 엣지·소스 정합성 + 멱등, 분리 후 소스 이동을 검증한다.
그래프 테이블은 이 개발 DB 에서 테스트 전용이므로 전체 초기화한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.graph.moderation import merge_issues, split_issue
from app.models.entity import Entity as EntityModel
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource


@pytest.fixture()
def graph():
    """빈 그래프에 엔터티 2개 + 이슈 A/B 를 소스·엣지와 함께 구성."""
    with SessionLocal() as s:
        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(EntityModel))
        e1 = EntityModel(type="sector", name="증권", canonical_name="증권")
        e2 = EntityModel(type="regulation", name="자본시장법",
                         canonical_name="자본시장과 금융투자업에 관한 법률")
        s.add_all([e1, e2])
        s.flush()

        a = Issue(title="이슈 A")
        b = Issue(title="이슈 B")
        s.add_all([a, b])
        s.flush()

        # A: 소스 pr#1, 엔터티 e1(affects)
        s.add(IssueSource(issue_id=a.id, source_type="press_release", source_id=1, relation="trigger"))
        s.add(IssueEntity(issue_id=a.id, entity_id=e1.id, relation="affects"))
        # B: 소스 pr#2, 엔터티 e1(affects, A와 중복) + e2(based_on)
        s.add(IssueSource(issue_id=b.id, source_type="press_release", source_id=2, relation="trigger"))
        s.add(IssueEntity(issue_id=b.id, entity_id=e1.id, relation="affects"))
        s.add(IssueEntity(issue_id=b.id, entity_id=e2.id, relation="based_on"))
        s.commit()

        yield {"a": a.id, "b": b.id, "e1": e1.id, "e2": e2.id}

        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(EntityModel))
        s.commit()


def _counts(session, issue_id):
    src = session.execute(
        select(IssueSource).where(IssueSource.issue_id == issue_id)
    ).scalars().all()
    ent = session.execute(
        select(IssueEntity).where(IssueEntity.issue_id == issue_id)
    ).scalars().all()
    return src, ent


def test_merge_moves_edges_and_dedupes(graph) -> None:
    with SessionLocal() as s:
        res = merge_issues(s, source_id=graph["b"], target_id=graph["a"])
        s.commit()

    assert res["merged"] is True
    assert res["moved_sources"] == 1  # pr#2 이동
    assert res["moved_entities"] == 1  # e2(based_on) 이동
    assert res["dropped_dup_entities"] == 1  # e1(affects) 중복 제거

    with SessionLocal() as s:
        # source(B) 삭제됨
        assert s.get(Issue, graph["b"]) is None
        src, ent = _counts(s, graph["a"])
        # 소스: pr#1 + pr#2
        assert {(r.source_type, r.source_id) for r in src} == {("press_release", 1), ("press_release", 2)}
        # 엔터티: e1(affects) 1개(중복 아님) + e2(based_on)
        keys = sorted((r.entity_id, r.relation) for r in ent)
        assert keys == sorted([(graph["e1"], "affects"), (graph["e2"], "based_on")])
        # 고아 엣지 없음(B 참조 0)
        orphan = s.execute(select(IssueEntity).where(IssueEntity.issue_id == graph["b"])).scalars().all()
        assert orphan == []


def test_merge_is_idempotent(graph) -> None:
    with SessionLocal() as s:
        merge_issues(s, source_id=graph["b"], target_id=graph["a"])
        s.commit()
    # 재실행: B 이미 없음 → no-op
    with SessionLocal() as s:
        res2 = merge_issues(s, source_id=graph["b"], target_id=graph["a"])
        s.commit()
    assert res2["merged"] is False
    assert res2["reason"] == "source_not_found"


def test_merge_same_issue_raises(graph) -> None:
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            merge_issues(s, source_id=graph["a"], target_id=graph["a"])


def test_split_moves_selected_source(graph) -> None:
    # 먼저 A 에 소스 2개가 되도록 B 를 A 로 병합
    with SessionLocal() as s:
        merge_issues(s, source_id=graph["b"], target_id=graph["a"])
        s.commit()

    with SessionLocal() as s:
        # A 의 pr#2 소스 행을 분리 대상으로
        src2 = s.execute(
            select(IssueSource).where(
                IssueSource.issue_id == graph["a"], IssueSource.source_id == 2
            )
        ).scalar_one()
        res = split_issue(s, graph["a"], [src2.id], new_title="분리된 이슈")
        s.commit()
        new_id = res["new_issue_id"]

    with SessionLocal() as s:
        # 원본 A: pr#1 만 남음
        a_src, a_ent = _counts(s, graph["a"])
        assert {r.source_id for r in a_src} == {1}
        # 신규 이슈: pr#2 이동 + 엔터티 태깅 복사
        n_src, n_ent = _counts(s, new_id)
        assert {r.source_id for r in n_src} == {2}
        assert len(n_ent) == len(a_ent)  # 태깅 복사됨(양쪽 유지)
        assert s.get(Issue, new_id).title == "분리된 이슈"


def test_split_all_sources_raises(graph) -> None:
    with SessionLocal() as s:
        only_src = s.execute(
            select(IssueSource).where(IssueSource.issue_id == graph["a"])
        ).scalar_one()  # A 는 소스 1개뿐
        with pytest.raises(ValueError):
            split_issue(s, graph["a"], [only_src.id])
