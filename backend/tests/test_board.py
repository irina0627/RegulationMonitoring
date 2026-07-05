"""보도자료 상세 수집기 단위 테스트 (네트워크 없음).

저장된 상세 페이지 HTML 픽스처로 담당부서·첨부파일 파싱을 검증한다.
"""

from __future__ import annotations

from pathlib import Path

from app.collectors.board import collect_detail, parse_detail

FIXTURE = Path(__file__).parent / "fixtures" / "fsc_board_detail.html"
BASE_URL = "https://www.fsc.go.kr/no010101/87252"


def _html() -> bytes:
    return FIXTURE.read_bytes()


def test_parse_detail_extracts_dept() -> None:
    detail = parse_detail(_html(), BASE_URL)
    assert detail["dept"] == "금융정책과"  # 담당자/등록일이 아닌 담당부서만


def test_parse_detail_extracts_attachments() -> None:
    detail = parse_detail(_html(), BASE_URL)
    atts = detail["attachments"]
    # 첨부 2건 (파일명 링크만; '파일다운로드' 중첩 링크는 제외)
    assert len(atts) == 2

    hwp, pdf = atts
    assert hwp["type"] == "hwp"
    assert hwp["filename"].endswith(".hwp")
    assert hwp["url"] == (
        "https://www.fsc.go.kr/comm/getFile?srvcId=BBSTY1&upperNo=87252&fileTy=ATTACH&fileNo=1"
    )

    assert pdf["type"] == "pdf"
    assert pdf["url"].endswith("fileNo=2")


def test_parse_detail_missing_structure_returns_empty() -> None:
    # 구조가 바뀌어 선택자가 안 맞아도 예외 없이 빈 값
    detail = parse_detail("<html><body>no data</body></html>", BASE_URL)
    assert detail["dept"] is None
    assert detail["attachments"] == []


def test_collect_detail_merges_into_record() -> None:
    # 실제 병합 로직은 순수 파싱 결과와 합쳐지는지만 확인 (fetch 는 건드리지 않음)
    record = {
        "rss_guid": "abc123",
        "title": "PF 점검회의",
        "published_at": None,
        "source_url": BASE_URL,
    }
    # fetch_detail 를 픽스처로 대체
    import app.collectors.board as board

    orig = board.fetch_detail
    board.fetch_detail = lambda url, **kw: _html()
    try:
        merged = collect_detail(record)
    finally:
        board.fetch_detail = orig

    # 기존 rss 레코드 키 유지 + dept/attachments 추가
    assert merged["rss_guid"] == "abc123"
    assert merged["title"] == "PF 점검회의"
    assert merged["dept"] == "금융정책과"
    assert len(merged["attachments"]) == 2


def test_collect_detail_without_source_url() -> None:
    record = {"rss_guid": "x", "title": "t", "published_at": None, "source_url": None}
    merged = collect_detail(record)
    assert merged["dept"] is None
    assert merged["attachments"] == []
