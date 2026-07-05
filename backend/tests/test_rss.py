"""RSS 수집기 단위 테스트 (네트워크 없음).

픽스처 XML 로 파싱·guid 폴백·신규 판별을 검증한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.collectors.rss import parse_feed, select_new, to_record

FIXTURE = Path(__file__).parent / "fixtures" / "fsc_press_sample.xml"


def _load() -> list[dict]:
    return parse_feed(FIXTURE.read_bytes())


def test_parse_feed_returns_standard_records() -> None:
    records = _load()
    assert len(records) == 2

    first = records[0]
    # 표준 레코드 키 4종
    assert set(first.keys()) == {"rss_guid", "title", "published_at", "source_url"}
    assert first["title"] == "가상자산이용자보호법 시행령 입법예고"
    assert first["source_url"] == "https://www.fsc.go.kr/no010101/80001"
    # guid 존재 항목 → link 를 그대로 guid 로
    assert first["rss_guid"] == "https://www.fsc.go.kr/no010101/80001"


def test_published_at_is_tz_aware_utc() -> None:
    first = _load()[0]
    pub = first["published_at"]
    assert isinstance(pub, datetime)
    assert pub.tzinfo is not None
    # 2025-06-30 09:00 KST(+0900) → 2025-06-30 00:00 UTC
    assert pub == datetime(2025, 6, 30, 0, 0, 0, tzinfo=timezone.utc)


def test_guid_falls_back_to_link_hash() -> None:
    second = _load()[1]  # guid 없는 항목
    link = "https://www.fsc.go.kr/no010101/80002"
    expected = hashlib.sha256(link.encode("utf-8")).hexdigest()
    assert second["rss_guid"] == expected


def test_select_new_filters_existing() -> None:
    records = _load()
    existing = {"https://www.fsc.go.kr/no010101/80001"}  # 첫 항목은 이미 저장됨
    new = select_new(records, existing)
    # 두 번째(해시 guid)만 신규
    assert len(new) == 1
    assert new[0]["title"] == "금융소비자보호법 관련 안내(guid 없음)"


def test_select_new_all_new_when_empty_db() -> None:
    records = _load()
    assert select_new(records, set()) == records


def test_to_record_without_guid_and_link() -> None:
    # link 도 guid 도 없으면 rss_guid 는 None
    rec = to_record({"title": "제목만"})
    assert rec == {
        "rss_guid": None,
        "title": "제목만",
        "published_at": None,
        "source_url": None,
    }
