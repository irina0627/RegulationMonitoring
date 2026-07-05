"""LLM 어댑터 테스트 (실제 API 호출 없음).

- 팩토리 get_llm_client() → OpenAIClient.
- 4개 작업 메서드의 JSON 파싱·스키마 검증(_chat_json mock).
- 스키마 불일치 시 1회 재시도 → 안전 폴백.
- validation 유틸 단위 검증.
"""

from __future__ import annotations

import pytest

from app.nlp import get_llm_client
from app.nlp.llm_client import Entity, Impact, LLMClient, Summary
from app.nlp.openai_client import OpenAIClient
from app.nlp.validation import (
    SchemaError,
    parse_entities,
    parse_impact,
    parse_lifecycle,
    parse_summary,
)


# --- 팩토리 --------------------------------------------------------------- #
def test_factory_returns_openai_client() -> None:
    client = get_llm_client("openai")
    assert isinstance(client, OpenAIClient)
    assert isinstance(client, LLMClient)  # 구조적 인터페이스 만족


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        get_llm_client("nope")


# --- 인터페이스 파싱 (mock) ----------------------------------------------- #
@pytest.fixture()
def client(monkeypatch) -> OpenAIClient:
    c = get_llm_client("openai")
    canned = {
        "summarize": {
            "summary": "가상자산 시세조종 혐의자 고발",
            "why_it_matters": "가상자산 업권 컴플라이언스에 직접 영향",
        },
        "entities": {
            "entities": [
                {"type": "sector", "name": "가상자산", "canonical_name": None},
                {"type": "REGULATION", "name": "가상자산이용자보호법",  # 대문자 → 정규화
                 "canonical_name": "가상자산 이용자 보호 등에 관한 법률",
                 "enforce_date": "2024-07-19"},
                {"type": "", "name": "무효(누락되어야)"},  # type 없음 → 제외
            ]
        },
        "lifecycle": {"stage_code": "follow_up"},  # 소문자 → 정규화
        "impact": {"sectors": ["가상자산", " "], "products": ["코인"],
                   "rationale": "시세조종 단속 강화"},
    }

    def fake(system: str, user: str) -> dict:
        if "summary" in system and "why_it_matters" in system:
            return canned["summarize"]
        if "엔터티" in system:
            return canned["entities"]
        if "stage_code" in system:
            return canned["lifecycle"]
        if "sectors" in system:
            return canned["impact"]
        return {}

    monkeypatch.setattr(c, "_chat_json", fake)
    return c


def test_summarize(client: OpenAIClient) -> None:
    out = client.summarize("본문")
    assert isinstance(out, Summary)
    assert out.summary == "가상자산 시세조종 혐의자 고발"


def test_extract_entities(client: OpenAIClient) -> None:
    out = client.extract_entities("본문")
    assert all(isinstance(e, Entity) for e in out)
    assert len(out) == 2  # type 없는 항목 제외
    assert out[1].type == "regulation"  # 소문자 정규화
    assert out[1].enforce_date == "2024-07-19"


def test_classify_lifecycle_normalizes(client: OpenAIClient) -> None:
    assert client.classify_lifecycle("본문") == "FOLLOW_UP"


def test_assess_impact(client: OpenAIClient) -> None:
    out = client.assess_impact("본문")
    assert isinstance(out, Impact)
    assert out.sectors == ["가상자산"]  # 공백 항목 제거
    assert out.products == ["코인"]


# --- 재시도 → 폴백 -------------------------------------------------------- #
def test_bad_shape_falls_back_to_empty(monkeypatch) -> None:
    c = get_llm_client("openai")
    calls = {"n": 0}

    def always_bad(system: str, user: str) -> dict:
        calls["n"] += 1
        return {}  # 스키마 불일치

    monkeypatch.setattr(c, "_chat_json", always_bad)
    out = c.summarize("본문")
    assert out == Summary(summary="", why_it_matters="")  # 안전 폴백
    assert calls["n"] == 2  # 최초 + 재시도 1회


def test_retry_recovers_on_second_attempt(monkeypatch) -> None:
    c = get_llm_client("openai")
    seq = [{}, {"stage_code": "ENFORCEMENT"}]  # 1차 불량 → 2차 정상

    def flaky(system: str, user: str) -> dict:
        return seq.pop(0)

    monkeypatch.setattr(c, "_chat_json", flaky)
    assert c.classify_lifecycle("본문") == "ENFORCEMENT"


# --- validation 유틸 ------------------------------------------------------ #
def test_parse_summary_missing_keys() -> None:
    with pytest.raises(SchemaError):
        parse_summary({"summary": "x"})  # why_it_matters 없음


def test_parse_summary_empty_summary() -> None:
    with pytest.raises(SchemaError):
        parse_summary({"summary": "  ", "why_it_matters": "y"})


def test_parse_summary_strips_reader_reference() -> None:
    out = parse_summary({
        "summary": "요약",
        "why_it_matters": "증권사 임직원은 관련 규제 대응이 필요하다.",
    })
    assert out.why_it_matters == "관련 규제 대응이 필요하다."
    assert "증권사 임직원" not in out.why_it_matters

    out2 = parse_summary({"summary": "s", "why_it_matters": "임직원들은, 리스크를 점검해야 한다."})
    assert out2.why_it_matters == "리스크를 점검해야 한다."


def test_parse_lifecycle_invalid() -> None:
    with pytest.raises(SchemaError):
        parse_lifecycle({"stage_code": "ZZZ"})


def test_parse_impact_missing_key() -> None:
    with pytest.raises(SchemaError):
        parse_impact({"sectors": [], "products": []})  # rationale 없음


def test_parse_entities_skips_invalid_items() -> None:
    out = parse_entities(
        {"entities": [
            {"type": "sector", "name": "증권"},
            {"type": "unknown", "name": "x"},  # 잘못된 type → 제외
            "not-a-dict",  # 무시
        ]}
    )
    assert len(out) == 1
    assert out[0].name == "증권"


def test_parse_entities_missing_array() -> None:
    with pytest.raises(SchemaError):
        parse_entities({"foo": 1})
