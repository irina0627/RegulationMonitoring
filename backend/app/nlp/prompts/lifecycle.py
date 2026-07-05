"""라이프사이클 분류 프롬프트: stage_code 1차 추정."""

from __future__ import annotations

from app.nlp.prompts._base import BASE_SYSTEM

LIFECYCLE_SYSTEM = (
    BASE_SYSTEM
    + """

[작업] 규제 라이프사이클 단계를 본문 단서로 1차 추정한다. 가장 적합한 하나만 고른다.

[단계 코드 — 의미]
- PRE_NOTICE   : 입법예고 / 규정변경예고
- DECISION     : 금융위·증선위 의결 / 국무회의 (법률은 국회 단계 포함)
- PROMULGATION : 공포
- SUB_LAW      : 시행령·시행규칙·고시 정비
- ENFORCEMENT  : 시행
- FOLLOW_UP    : 가이드라인·FAQ·검사 등 후속

[출력 JSON 스키마]
{"stage_code": "<위 코드 중 정확히 하나>"}
"""
)
