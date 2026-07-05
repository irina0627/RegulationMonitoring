"""다이제스트 구성·렌더 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.email.digest import (
    DigestData,
    DigestItem,
    build_digest,
    render_digest,
)
from app.models.entity import Entity
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.models.press_release import PressRelease


# --- 렌더링 (DB 없음) ----------------------------------------------------- #
def _sample_data() -> DigestData:
    return DigestData(
        group_name="파생업권",
        count=1,
        items=[
            DigestItem(
                issue_id=1,
                title="ELS 판매규제 강화 <검토>",  # 이스케이프 확인용 < >
                summary="주가연계증권 판매비중 규제를 강화한다.",
                why_it_matters="증권 상품 컴플라이언스에 직접 영향",
                stage_code="DECISION",
                stage_label="의결",
                stage_color="#2563eb",
                sectors=["증권"],
                products=["ELS"],
                source_label="1차 · 금융위 보도자료",
                source_url="https://www.fsc.go.kr/no010101/12345",
                published_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
            )
        ],
    )


def test_render_contains_core_fields() -> None:
    html = render_digest(_sample_data())
    assert "오늘의 핵심 1건" in html
    assert "파생업권 다이제스트" in html
    assert "주가연계증권 판매비중 규제를 강화한다." in html
    assert "왜 중요한가" in html
    assert "단계: 의결" in html  # 색만 아니라 텍스트 라벨 병기
    assert "업권: 증권" in html
    assert "상품: ELS" in html
    assert "1차 · 금융위 보도자료" in html
    assert "https://www.fsc.go.kr/no010101/12345" in html
    # 면책
    assert "투자권유가 아닙니다" in html
    # HTML 이스케이프(제목의 < > )
    assert "&lt;검토&gt;" in html
    assert "<검토>" not in html


def test_render_empty_digest() -> None:
    html = render_digest(DigestData(group_name="컴플라이언스", count=0, items=[]))
    assert "오늘의 핵심 0건" in html
    assert "신규 규제 이슈가 없습니다" in html


# --- build_digest (DB) ---------------------------------------------------- #
@pytest.fixture()
def seeded_db():
    with SessionLocal() as s:
        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(Entity))
        s.execute(delete(PressRelease).where(PressRelease.rss_guid.like("test-digest-%")))

        # 엔터티: ELS(등록), 서민금융(미등록 플래그), 은행(등록)
        els = Entity(type="product", name="ELS", canonical_name="ELS")
        seomin = Entity(type="sector", name="서민금융", canonical_name="서민금융",
                        meta={"unregistered": True})
        bank = Entity(type="sector", name="은행", canonical_name="은행")
        s.add_all([els, seomin, bank])
        s.flush()

        # 소스 보도자료
        pr = PressRelease(rss_guid="test-digest-1", title="ELS 규제",
                          source_url="https://fsc.go.kr/x/1",
                          published_at=datetime(2026, 7, 3, tzinfo=timezone.utc))
        s.add(pr)
        s.flush()

        # 이슈 A: ELS 관련 (매칭 대상), 최신
        a = Issue(title="ELS 판매규제", summary="ELS 규제 강화",
                  why_it_matters="증권 영향", lifecycle_stage="DECISION")
        # 이슈 B: 은행 (그룹 미매칭)
        b = Issue(title="은행 이슈", summary="은행", lifecycle_stage="DECISION")
        # 이슈 C: ELS 관련이나 오래됨 (since 이전)
        old = datetime(2026, 6, 1, tzinfo=timezone.utc)
        c = Issue(title="옛 ELS 이슈", summary="과거", lifecycle_stage="DECISION",
                  first_seen_at=old, last_updated_at=old)
        s.add_all([a, b, c])
        s.flush()

        s.add_all([
            IssueEntity(issue_id=a.id, entity_id=els.id, relation="affects"),
            IssueEntity(issue_id=a.id, entity_id=seomin.id, relation="affects"),  # 미등록
            IssueEntity(issue_id=b.id, entity_id=bank.id, relation="affects"),
            IssueEntity(issue_id=c.id, entity_id=els.id, relation="affects"),
            IssueSource(issue_id=a.id, source_type="press_release", source_id=pr.id, relation="trigger"),
        ])
        s.commit()
        ids = {"a": a.id, "b": b.id, "c": c.id}

    yield ids

    with SessionLocal() as s:
        s.execute(delete(IssueEntity))
        s.execute(delete(IssueSource))
        s.execute(delete(Issue))
        s.execute(delete(Entity))
        s.execute(delete(PressRelease).where(PressRelease.rss_guid.like("test-digest-%")))
        s.commit()


def test_build_digest_matches_group_and_since(seeded_db) -> None:
    group = {"name": "파생업권", "products": ["ELS"]}
    since = datetime(2026, 7, 1, tzinfo=timezone.utc)
    with SessionLocal() as s:
        data = build_digest(s, group, since)

    # A 만: B(미매칭), C(since 이전) 제외
    assert data.count == 1
    item = data.items[0]
    assert item.issue_id == seeded_db["a"]
    assert item.products == ["ELS"]
    assert item.sectors == []  # 서민금융(미등록)은 제외
    assert item.source_label == "1차 · 금융위 보도자료"
    assert item.source_url == "https://fsc.go.kr/x/1"


def test_build_digest_renders(seeded_db) -> None:
    group = {"name": "파생업권", "products": ["ELS"]}
    with SessionLocal() as s:
        data = build_digest(s, group, since=datetime(2026, 7, 1, tzinfo=timezone.utc))
        html = render_digest(data)
    assert "ELS 판매규제" in html
    assert "오늘의 핵심 1건" in html
