"""시드 온톨로지 정규화 테스트 (설계서 6.5)."""

from __future__ import annotations

import pytest

from app.nlp.entity import Normalized, is_registered, normalize_entity


# --- 약칭 → 정식 (법령) --------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("자본시장법", "자본시장과 금융투자업에 관한 법률"),
        ("금소법", "금융소비자 보호에 관한 법률"),
        ("전금법", "전자금융거래법"),
        ("신용정보법", "신용정보의 이용 및 보호에 관한 법률"),
        ("가상자산이용자보호법", "가상자산 이용자 보호 등에 관한 법률"),
    ],
)
def test_regulation_abbrev_to_canonical(raw: str, expected: str) -> None:
    out = normalize_entity("regulation", raw)
    assert out.registered is True
    assert out.canonical_name == expected


def test_regulation_full_name_with_spaces() -> None:
    # 공백이 섞여도 매칭
    out = normalize_entity("regulation", "자본시장과  금융투자업에 관한  법률")
    assert out.canonical_name == "자본시장과 금융투자업에 관한 법률"
    assert out.registered


# --- 동의어 → 대표어 (업권) ----------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("금융투자업권", "증권"),
        ("증권사", "증권"),
        ("인터넷전문은행", "은행"),
        ("코인", "가상자산"),
        ("전자금융업", "핀테크"),
        ("여신전문금융", "카드·여전"),
    ],
)
def test_sector_synonym_to_canonical(raw: str, expected: str) -> None:
    out = normalize_entity("sector", raw)
    assert out.registered is True
    assert out.canonical_name == expected


# --- 상품 --------------------------------------------------------------- #
def test_product_synonym() -> None:
    assert normalize_entity("product", "주가연계증권").canonical_name == "ELS"
    assert normalize_entity("product", "els").canonical_name == "ELS"  # 대소문자 무시


# --- 기관 구명칭 → 현행명 (E3 보정) --------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("재정경제부", "기획재정부"),
        ("노동부", "고용노동부"),
        ("중기부", "중소벤처기업부"),
        ("금융위", "금융위원회"),
        ("금감원", "금융감독원"),
    ],
)
def test_agency_old_name_to_current(raw: str, expected: str) -> None:
    out = normalize_entity("agency", raw)
    assert out.registered is True
    assert out.canonical_name == expected


# --- 미등록 → 플래그 ------------------------------------------------------ #
@pytest.mark.parametrize(
    "etype,raw",
    [
        ("sector", "서민금융"),  # 온톨로지 밖
        ("sector", "인터넷은행 대면업무 합리적 조정 방안"),  # 정책명 오태깅
        ("agency", "기획처"),  # 비존재/축약 오류
        ("regulation", "가상자산시장 시세조종 혐의자 수사기관 고발"),  # 제목 오태깅
        ("product", "생성형 AI"),  # 상품 아님
    ],
)
def test_unregistered_is_flagged(etype: str, raw: str) -> None:
    out = normalize_entity(etype, raw)
    assert out.registered is False
    assert out.canonical_name == raw.strip()  # 원시명 유지


def test_empty_name() -> None:
    out = normalize_entity("sector", "  ")
    assert out.registered is False
    assert out.canonical_name == ""


def test_is_registered_helper() -> None:
    assert is_registered("regulation", "자본시장법") is True
    assert is_registered("sector", "없는업권") is False


def test_returns_dataclass() -> None:
    out = normalize_entity("sector", "증권")
    assert isinstance(out, Normalized)
    assert out.type == "sector"
    assert out.raw == "증권"
