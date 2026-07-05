"""LLM JSON 출력 파싱·스키마 검증 유틸 (설계서 12.2·12.3).

각 parser 는 LLM 이 돌려준 dict 를 검증해 타입 객체로 변환한다.
형식이 어긋나면 SchemaError 를 던진다 → 호출부(OpenAIClient)가 1회 재시도, 그래도 실패면 안전 폴백.
"""

from __future__ import annotations

import re
from typing import Any

from app.nlp.llm_client import (
    ENTITY_TYPES,
    LIFECYCLE_STAGES,
    Entity,
    Impact,
    Summary,
)


class SchemaError(ValueError):
    """LLM 출력이 기대 스키마와 맞지 않을 때."""


# 문두의 '증권사 임직원…' 등 독자 지칭 표현 제거(방어적)
_READER_PREFIX = re.compile(
    r"^\s*(증권사\s*)?임직원(들)?(은|는|이|에게는|에게도|에게|께서|께)?\s*[,·]?\s*"
)


def _strip_reader_ref(text: str) -> str:
    """'증권사 임직원은 ~' 같은 문두 독자 지칭을 제거한다."""
    return _READER_PREFIX.sub("", text).strip()


# --- 원시 헬퍼 ------------------------------------------------------------- #
def _as_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _as_str_list(v: Any, field: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise SchemaError(f"{field} 는 배열이어야 함")
    return [s for s in (_as_str(x) for x in v) if s]


def _require_dict(data: Any) -> dict:
    if not isinstance(data, dict):
        raise SchemaError("최상위가 JSON 객체가 아님")
    return data


# --- 작업별 parser (검증 + 변환) ------------------------------------------ #
def parse_summary(data: Any) -> Summary:
    d = _require_dict(data)
    if "summary" not in d or "why_it_matters" not in d:
        raise SchemaError("summary/why_it_matters 키 누락")
    summary = _as_str(d["summary"])
    if not summary:
        raise SchemaError("summary 가 비어 있음")
    why = _strip_reader_ref(_as_str(d["why_it_matters"]))
    return Summary(summary=summary, why_it_matters=why)


def parse_entities(data: Any) -> list[Entity]:
    d = _require_dict(data)
    items = d.get("entities")
    if not isinstance(items, list):
        raise SchemaError("entities 배열 누락")
    result: list[Entity] = []
    for e in items:
        if not isinstance(e, dict):
            continue
        etype = _as_str(e.get("type")).lower()
        name = _as_str(e.get("name"))
        if etype not in ENTITY_TYPES or not name:
            continue  # 잘못된 개별 항목은 조용히 건너뜀(전체 재시도까진 아님)
        canonical = _as_str(e.get("canonical_name")) or None
        enforce = _as_str(e.get("enforce_date")) or None
        result.append(
            Entity(type=etype, name=name, canonical_name=canonical, enforce_date=enforce)
        )
    return result  # 빈 리스트도 유효(엔터티 없을 수 있음)


def parse_lifecycle(data: Any) -> str:
    d = _require_dict(data)
    if "stage_code" not in d:
        raise SchemaError("stage_code 키 누락")
    stage = _as_str(d["stage_code"]).upper()
    if stage not in LIFECYCLE_STAGES:
        raise SchemaError(f"허용되지 않은 stage_code: {stage!r}")
    return stage


def parse_impact(data: Any) -> Impact:
    d = _require_dict(data)
    for key in ("sectors", "products", "rationale"):
        if key not in d:
            raise SchemaError(f"{key} 키 누락")
    return Impact(
        sectors=_as_str_list(d["sectors"], "sectors"),
        products=_as_str_list(d["products"], "products"),
        rationale=_as_str(d["rationale"]),
    )
