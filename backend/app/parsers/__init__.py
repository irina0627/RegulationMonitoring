"""파서 레이어 통합 진입점 (설계서 7장).

parse_attachments: 같은 보도자료의 첨부들에서 본문 텍스트를 추출한다.
전략(7.2): PDF 우선 시도 → 실패 시 HWP/HWPX 폴백. 모두 실패하면
빈 본문 + parse_status='failed' 를 반환한다(예외로 파이프라인을 멈추지 않음).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.parsers.hwp import extract_hwp_text
from app.parsers.pdf import extract_pdf_text

log = get_logger(__name__)

Attachment = dict[str, Any]

# 시도 우선순위: PDF > HWPX > HWP
_PRIORITY = {"pdf": 0, "hwpx": 1, "hwp": 2}


def _kind_of(att: Attachment) -> str | None:
    """첨부의 파서 종류(pdf/hwpx/hwp) 판별. type → filename/local_path 확장자 순."""
    t = (att.get("type") or "").lower()
    if t in _PRIORITY:
        return t
    for key in ("filename", "local_path", "url"):
        val = att.get(key)
        if val and "." in val:
            ext = val.rsplit(".", 1)[-1].lower()
            if ext in _PRIORITY:
                return ext
    return None


def _extract_one(kind: str, path: str) -> str:
    return extract_pdf_text(path) if kind == "pdf" else extract_hwp_text(path)


def parse_attachments(attachments: list[Attachment]) -> dict:
    """첨부 목록에서 본문 텍스트를 추출한다.

    반환: {"body_text": str, "parse_status": "parsed"|"failed", "source_file": str|None}
    - 다운로드된(local_path 존재) 첨부만 시도한다.
    - PDF 우선, 실패 시 HWPX/HWP 폴백. 모두 실패/무첨부면 failed.
    """
    # 다운로드된 첨부만, 우선순위대로 정렬
    candidates = [
        (kind, att)
        for att in attachments
        if att.get("local_path") and (kind := _kind_of(att)) is not None
    ]
    candidates.sort(key=lambda ka: _PRIORITY[ka[0]])

    for kind, att in candidates:
        path = att["local_path"]
        if not Path(path).exists():
            log.warning("첨부 경로 없음(스킵): %s", path)
            continue
        try:
            text = _extract_one(kind, path)
        except Exception as exc:  # noqa: BLE001 - 폴백 위해 포착
            log.warning("본문 추출 실패(%s), 폴백 시도: %s", kind, exc)
            continue
        if text.strip():
            log.info("본문 추출 성공: %s (%s)", Path(path).name, kind)
            return {"body_text": text, "parse_status": "parsed", "source_file": path}
        log.warning("본문이 비어 있음(%s), 폴백 시도: %s", kind, path)

    log.error("모든 첨부 본문 추출 실패 — parse_status=failed (첨부 %d건)", len(attachments))
    return {"body_text": "", "parse_status": "failed", "source_file": None}
