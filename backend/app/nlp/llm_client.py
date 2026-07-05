"""LLM 어댑터 인터페이스 (설계서 12장).

코어 NLP 로직은 이 `LLMClient` 인터페이스에만 의존한다.
외부 LLM 호출은 구현체(openai_client.OpenAIClient)에만 존재한다.
사내망 이전 시 OnPremClient/RuleBasedClient 로 교체 가능(3.2 어댑터 격리).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# 라이프사이클 stage_code (설계서 6.3)
LIFECYCLE_STAGES: tuple[str, ...] = (
    "PRE_NOTICE",  # 입법예고 / 규정변경예고
    "DECISION",  # 의결 / 국무회의
    "PROMULGATION",  # 공포
    "SUB_LAW",  # 시행령·시행규칙·고시
    "ENFORCEMENT",  # 시행
    "FOLLOW_UP",  # 가이드라인·FAQ·검사 등 후속
)


@dataclass
class Summary:
    """한 줄 요약 + '왜 중요한가'(임직원 관점)."""

    summary: str
    why_it_matters: str


@dataclass
class Entity:
    """추출 엔터티. type: regulation|product|sector|agency|dept.

    enforce_date: 법령 등의 시행일(본문에 있으면 ISO YYYY-MM-DD, 없으면 None).
    """

    type: str
    name: str
    canonical_name: str | None = None
    enforce_date: str | None = None


# 유효한 엔터티 타입 (설계서 8장 entity.type)
ENTITY_TYPES: frozenset[str] = frozenset(
    {"regulation", "product", "sector", "agency", "dept"}
)


@dataclass
class Impact:
    """영향 추정: 어떤 업권·상품에, 근거 문장과 함께."""

    sectors: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    rationale: str = ""


@runtime_checkable
class LLMClient(Protocol):
    """NLP 코어가 의존하는 유일한 LLM 인터페이스."""

    def summarize(self, text: str) -> Summary:
        """본문 → 한 줄 요약 + 왜 중요한가."""
        ...

    def extract_entities(self, text: str) -> list[Entity]:
        """본문 → 법령/상품/업권/기관/부서 엔터티 목록."""
        ...

    def classify_lifecycle(self, text: str) -> str:
        """본문 → 라이프사이클 stage_code (LIFECYCLE_STAGES 중 하나)."""
        ...

    def assess_impact(self, text: str) -> Impact:
        """본문 → 영향 업권·상품·근거."""
        ...
