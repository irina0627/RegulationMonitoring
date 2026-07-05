"""추출 텍스트 경량 정리.

과도한 공백·중복 빈 줄, 페이지번호/표·그림 placeholder 같은 가벼운 노이즈만 제거한다.
(본문 내용을 훼손하는 공격적 정리는 하지 않음)
"""

from __future__ import annotations

import re

# 페이지번호만 있는 줄: "1", "- 1 -", "12 / 30" 등
_PAGE_NUM = re.compile(r"^\s*-?\s*\d+\s*(/\s*\d+)?\s*-?\s*$")
# 표/그림 placeholder 만 있는 줄: "<표>", "<그림>", "[표]" 등
_PLACEHOLDER = re.compile(r"^\s*[<\[](표|그림|이미지)[>\]]\s*$")
# 줄 내부 연속 공백(탭·NBSP 포함)
_INLINE_WS = re.compile(r"[ \t 　]+")


def clean_text(text: str) -> str:
    """추출 텍스트를 가볍게 정리한다."""
    if not text:
        return ""

    # 제어문자(NUL 등) 제거. PostgreSQL text 는 NUL(0x00)을 저장할 수 없고
    # PDF/HWP 추출기가 섞어 넣을 수 있다. 개행·탭은 아래 로직에서 처리하므로 보존.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    cleaned_lines: list[str] = []
    prev_blank = False
    for raw in text.splitlines():
        line = _INLINE_WS.sub(" ", raw).strip()

        if _PAGE_NUM.match(line) or _PLACEHOLDER.match(line):
            continue

        if line == "":
            if prev_blank:
                continue  # 연속 빈 줄 1개로 축약
            prev_blank = True
        else:
            prev_blank = False
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()
