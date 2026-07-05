"""HWP/HWPX 본문 텍스트 추출 (설계서 7장).

- HWP(구형 바이너리): pyhwp(hwp5) 로 추출.
- HWPX(신형, XML 기반 zip): zip 해제 후 Contents/section*.xml 의 텍스트(hp:t) 추출.
  (pyhwp 는 hwpx 를 다루지 않으므로 표준 라이브러리로 처리 — 설계서 7.2 전략)
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.core.logging import get_logger
from app.parsers.textutil import clean_text

log = get_logger(__name__)

# pyhwp 의 시끄러운 경고(undefined UnderlineStyle 등) 억제
logging.getLogger("hwp5").setLevel(logging.ERROR)

# HWPX 본문 section XML 경로
_HWPX_SECTION = re.compile(r"Contents/section\d+\.xml$", re.IGNORECASE)


def _localname(tag: str) -> str:
    """{namespace}tag → tag."""
    return tag.rsplit("}", 1)[-1]


def extract_hwp_text(path: str | Path) -> str:
    """확장자에 따라 hwp/hwpx 본문 텍스트를 추출한다.

    실패 시 예외를 그대로 올린다(상위 orchestrator 가 폴백/failed 처리).
    """
    p = str(path)
    if p.lower().endswith(".hwpx"):
        return _extract_hwpx(p)
    return _extract_hwp5(p)


def _extract_hwpx(path: str) -> str:
    """HWPX(zip) 에서 문단(hp:p) 단위로 텍스트(hp:t)를 추출한다."""
    lines: list[str] = []
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if _HWPX_SECTION.search(n))
        if not sections:
            raise ValueError("HWPX 에 Contents/section*.xml 없음")
        for name in sections:
            root = ET.fromstring(z.read(name))
            for el in root.iter():
                if _localname(el.tag) == "p":  # 문단 = 한 줄
                    txt = "".join(
                        t.text or ""
                        for t in el.iter()
                        if _localname(t.tag) == "t"
                    )
                    if txt:
                        lines.append(txt)
    text = clean_text("\n".join(lines))
    log.info("HWPX 텍스트 추출: %s (%d자)", Path(path).name, len(text))
    return text


def _extract_hwp5(path: str) -> str:
    """구형 HWP(바이너리) 를 pyhwp 로 추출한다."""
    from hwp5.hwp5txt import TextTransform
    from hwp5.xmlmodel import Hwp5File

    hwp5file = Hwp5File(path)
    buf = io.BytesIO()
    TextTransform().transform_hwp5_to_text(hwp5file, buf)
    text = clean_text(buf.getvalue().decode("utf-8", "replace"))
    log.info("HWP 텍스트 추출: %s (%d자)", Path(path).name, len(text))
    return text
