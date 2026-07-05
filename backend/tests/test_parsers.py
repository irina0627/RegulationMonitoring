"""파서 레이어 단위 테스트.

소형 픽스처(pdf/hwpx/손상파일)로 추출·정리·폴백·graceful failed 를 검증한다.
"""

from __future__ import annotations

from pathlib import Path

from app.parsers import parse_attachments
from app.parsers.hwp import extract_hwp_text
from app.parsers.pdf import extract_pdf_text
from app.parsers.textutil import clean_text

FX = Path(__file__).parent / "fixtures"


# --- 개별 추출기 ---------------------------------------------------------- #
def test_extract_pdf_text() -> None:
    text = extract_pdf_text(FX / "sample.pdf")
    assert "FSC Press Release" in text
    assert "line one of the body text" in text
    # 페이지번호 "- 1 -" 노이즈는 정리로 제거
    assert "- 1 -" not in text


def test_extract_hwpx_text() -> None:
    text = extract_hwp_text(FX / "sample.hwpx")
    assert "한글 문서 본문 첫 줄입니다." in text
    # 같은 문단의 두 hp:t 는 이어붙음
    assert "두 번째 줄, 이어지는 텍스트." in text


# --- 텍스트 정리 ---------------------------------------------------------- #
def test_clean_text_collapses_whitespace_and_noise() -> None:
    raw = "제목\n\n\n본문   내용\n<표>\n42\n꼬리"
    out = clean_text(raw)
    assert "본문 내용" in out  # 연속 공백 축약
    assert "<표>" not in out  # placeholder 제거
    assert "\n42\n" not in f"\n{out}\n"  # 페이지번호 줄 제거
    assert "\n\n\n" not in out  # 연속 빈 줄 축약


# --- 통합 orchestrator ---------------------------------------------------- #
def test_parse_attachments_prefers_pdf() -> None:
    # pdf 와 hwpx 가 함께 있을 때 PDF 우선
    atts = [
        {"filename": "doc.hwpx", "type": "hwpx", "local_path": str(FX / "sample.hwpx")},
        {"filename": "doc.pdf", "type": "pdf", "local_path": str(FX / "sample.pdf")},
    ]
    result = parse_attachments(atts)
    assert result["parse_status"] == "parsed"
    assert result["source_file"].endswith("sample.pdf")  # PDF 가 먼저 성공
    assert "FSC Press Release" in result["body_text"]


def test_parse_attachments_falls_back_to_hwp_when_pdf_fails() -> None:
    # PDF 가 손상 → HWPX 로 폴백
    atts = [
        {"filename": "bad.pdf", "type": "pdf", "local_path": str(FX / "corrupt.pdf")},
        {"filename": "doc.hwpx", "type": "hwpx", "local_path": str(FX / "sample.hwpx")},
    ]
    result = parse_attachments(atts)
    assert result["parse_status"] == "parsed"
    assert result["source_file"].endswith("sample.hwpx")
    assert "한글 문서 본문" in result["body_text"]


def test_parse_attachments_all_fail_returns_failed() -> None:
    # 모든 첨부 실패 → graceful failed (예외 없음)
    atts = [{"filename": "bad.pdf", "type": "pdf", "local_path": str(FX / "corrupt.pdf")}]
    result = parse_attachments(atts)
    assert result["parse_status"] == "failed"
    assert result["body_text"] == ""
    assert result["source_file"] is None


def test_parse_attachments_no_downloaded_files() -> None:
    # local_path 없는(다운로드 안 된) 첨부만 → failed
    atts = [{"filename": "doc.pdf", "type": "pdf", "url": "http://x/doc.pdf"}]
    result = parse_attachments(atts)
    assert result["parse_status"] == "failed"


def test_parse_attachments_empty_list() -> None:
    result = parse_attachments([])
    assert result["parse_status"] == "failed"
    assert result["body_text"] == ""
