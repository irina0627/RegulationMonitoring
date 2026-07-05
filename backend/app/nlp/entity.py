"""시드 온톨로지 + 엔터티 정규화 (설계서 6.5).

추출된 원시 명칭을 표준 canonical_name 으로 매핑한다. 미등록 명칭은 플래그(registered=False).
M2 품질노트의 E2(온톨로지 밖 sector)·E3(구명칭 기관) 결함을 보정하는 1차 사전.
LLM 1차 추출 + 이 사전 2차 보정의 이중화 구조.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- 시드 온톨로지: canonical -> [원시/약칭/동의어] ------------------------- #

# 업권(sector)
SECTORS: dict[str, list[str]] = {
    "증권": ["증권", "증권업", "증권사", "금융투자", "금융투자업", "금융투자업권", "투자매매업"],
    "은행": ["은행", "은행업", "인터넷은행", "인터넷전문은행", "저축은행"],
    "보험": ["보험", "보험업", "생명보험", "손해보험", "보험사"],
    "카드·여전": ["카드", "카드사", "여전", "여신전문금융", "여신전문금융업", "캐피탈"],
    "자산운용": ["자산운용", "자산운용업", "운용사", "집합투자업"],
    "신탁": ["신탁", "신탁업"],
    "가상자산": ["가상자산", "가상자산업", "가상자산사업자", "가상통화", "암호화폐", "코인"],
    "핀테크": ["핀테크", "전자금융", "전자금융업", "전자금융업자"],
}

# 상품(product)
PRODUCTS: dict[str, list[str]] = {
    "ELS": ["ELS", "주가연계증권"],
    "ELB": ["ELB", "주가연계파생결합사채"],
    "DLS": ["DLS", "파생결합증권"],
    "펀드": ["펀드", "집합투자기구", "공모펀드", "사모펀드"],
    "신탁": ["신탁상품"],
    "CFD": ["CFD", "차액결제거래"],
    "랩": ["랩", "랩어카운트"],
    "IRP/연금": ["IRP", "개인형퇴직연금", "퇴직연금", "연금저축"],
    "채권": ["채권", "회사채", "국채", "회사채권"],
}

# 주요 법령(regulation): 정식명 -> [약칭/이표기]
REGULATIONS: dict[str, list[str]] = {
    "자본시장과 금융투자업에 관한 법률": ["자본시장법", "자본시장과 금융투자업에 관한 법률"],
    "금융소비자 보호에 관한 법률": ["금융소비자보호법", "금소법", "금융소비자 보호에 관한 법률"],
    "전자금융거래법": ["전자금융거래법", "전금법"],
    "신용정보의 이용 및 보호에 관한 법률": ["신용정보법", "신용정보의 이용 및 보호에 관한 법률"],
    "가상자산 이용자 보호 등에 관한 법률": [
        "가상자산이용자보호법", "가상자산법", "가상자산 이용자 보호 등에 관한 법률",
    ],
    "금융지주회사법": ["금융지주회사법", "금융지주법"],
    "개인채무자보호법": ["개인채무자보호법", "개인채무자 보호에 관한 법률"],
}

# 기관(agency): 현행 정식명 -> [구명칭/약칭] (E3 보정)
AGENCIES: dict[str, list[str]] = {
    "금융위원회": ["금융위원회", "금융위"],
    "금융감독원": ["금융감독원", "금감원"],
    "기획재정부": ["기획재정부", "기재부", "재정경제부", "재경부"],
    "고용노동부": ["고용노동부", "노동부"],
    "중소벤처기업부": ["중소벤처기업부", "중기부"],
    "산업통상자원부": ["산업통상자원부", "산업부"],
    "국토교통부": ["국토교통부", "국토부"],
    "증권선물위원회": ["증권선물위원회", "증선위"],
}

# type -> 온톨로지 테이블
_ONTOLOGY: dict[str, dict[str, list[str]]] = {
    "sector": SECTORS,
    "product": PRODUCTS,
    "regulation": REGULATIONS,
    "agency": AGENCIES,
    "dept": {},  # 부서는 board.py 구조 데이터 사용, 사전 매핑 없음
}


def _key(s: str | None) -> str:
    """매칭 키: 공백 제거 + casefold(대소문자 무시)."""
    return re.sub(r"\s+", "", s or "").casefold()


# type -> {alias_key: canonical}
_REVERSE: dict[str, dict[str, str]] = {}
for _etype, _table in _ONTOLOGY.items():
    _rev: dict[str, str] = {}
    for _canonical, _aliases in _table.items():
        _rev[_key(_canonical)] = _canonical
        for _a in _aliases:
            _rev[_key(_a)] = _canonical
    _REVERSE[_etype] = _rev


@dataclass
class Normalized:
    """정규화 결과."""

    type: str
    raw: str
    canonical_name: str  # 등록되면 표준명, 아니면 원시명 유지
    registered: bool  # 온톨로지 등록 여부(미등록=플래그)


def normalize_entity(etype: str, name: str) -> Normalized:
    """(type, 원시명) → 표준 canonical_name. 미등록이면 원시명 유지 + registered=False."""
    etype_l = (etype or "").strip().lower()
    raw = (name or "").strip()
    if not raw:
        return Normalized(etype_l, raw, "", False)

    canonical = _REVERSE.get(etype_l, {}).get(_key(raw))
    if canonical:
        return Normalized(etype_l, raw, canonical, True)
    return Normalized(etype_l, raw, raw, False)


def is_registered(etype: str, name: str) -> bool:
    """해당 (type, 명칭)이 온톨로지에 등록돼 있는지."""
    return _key(name) in _REVERSE.get((etype or "").strip().lower(), {})
