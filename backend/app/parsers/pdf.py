"""PDF 본문 텍스트 추출 (설계서 7장).

pdfplumber 로 페이지별 텍스트를 추출한다. 보도자료는 hwp·pdf 가 함께 첨부되는 경우가 많아
PDF 를 우선 시도한다(__init__.parse_attachments 참조).
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from app.core.logging import get_logger
from app.parsers.textutil import clean_text

log = get_logger(__name__)


def extract_pdf_text(path: str | Path) -> str:
    """PDF 파일에서 본문 텍스트를 추출해 정리된 문자열로 반환한다.

    추출 실패 시 예외를 그대로 올린다(상위 orchestrator 가 폴백/failed 처리).
    """
    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    text = clean_text("\n".join(parts))
    log.info("PDF 텍스트 추출: %s (%d자)", Path(path).name, len(text))
    return text
