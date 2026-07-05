"""그룹 ↔ 이슈 매칭 (설계서 10.2).

수신자 그룹의 filters {sectors, products, depts, keywords} 와 이슈의 엔터티/속성을 대조해
그 그룹에 보낼 이슈를 고르고 중요도순으로 정렬한다.

매칭: 이슈의 affects(업권·상품) / handled_by(부서) / 키워드가 filters 와 겹치면 매칭.
정렬 점수: 최신성 + 라이프사이클 단계 가중 + 영향도.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.nlp.entity import normalize_entity

log = get_logger(__name__)

# 라이프사이클 단계 가중 (설계서 6.3) — 정렬용
STAGE_WEIGHT = {
    "PRE_NOTICE": 1.0,
    "DECISION": 2.0,
    "PROMULGATION": 2.0,
    "SUB_LAW": 3.0,
    "ENFORCEMENT": 4.0,
    "FOLLOW_UP": 2.0,
    "": 1.0,
}
_MAX_STAGE = 4.0

# 정렬 가중 (최신성 / 단계 / 영향도)
W_RECENCY = 0.4
W_STAGE = 0.3
W_IMPACT = 0.3


@dataclass
class GroupFilters:
    sectors: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    depts: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class IssueView:
    """매칭·정렬에 필요한 이슈 뷰(엔터티 태그 포함)."""

    id: int | None
    title: str = ""
    summary: str = ""
    lifecycle_stage: str = ""
    sectors: list[str] = field(default_factory=list)  # affects 업권 canonical
    products: list[str] = field(default_factory=list)  # affects 상품 canonical
    depts: list[str] = field(default_factory=list)  # handled_by 부서
    published_at: datetime | None = None
    importance_score: float = 0.0

    @property
    def text(self) -> str:
        return f"{self.title} {self.summary}"


def _key(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def _canon_keys(values: list[str], etype: str | None) -> set[str]:
    """비교용 키 집합. sector/product 는 온톨로지 canonical 로 정규화 후 키화."""
    out: set[str] = set()
    for v in values or []:
        if not v or not v.strip():
            continue
        if etype in ("sector", "product"):
            v = normalize_entity(etype, v).canonical_name
        out.add(_key(v))
    return out


def _coerce_filters(group: Any) -> GroupFilters:
    """GroupFilters / dict / recipient_group(model) 어느 형태든 GroupFilters 로."""
    if isinstance(group, GroupFilters):
        return group
    d = group if isinstance(group, dict) else getattr(group, "filters", None)
    d = d or {}
    return GroupFilters(
        sectors=list(d.get("sectors", []) or []),
        products=list(d.get("products", []) or []),
        depts=list(d.get("depts", []) or []),
        keywords=list(d.get("keywords", []) or []),
    )


def match_reasons(filters: GroupFilters, issue: IssueView) -> list[str]:
    """이슈가 filters 와 겹치는 근거 목록(없으면 빈 리스트 = 매칭 안 됨)."""
    reasons: list[str] = []

    if _canon_keys(filters.sectors, "sector") & _canon_keys(issue.sectors, "sector"):
        reasons.append("sector")
    if _canon_keys(filters.products, "product") & _canon_keys(issue.products, "product"):
        reasons.append("product")
    if _canon_keys(filters.depts, None) & _canon_keys(issue.depts, None):
        reasons.append("dept")

    text = issue.text.casefold()
    if any(kw.strip() and kw.strip().casefold() in text for kw in filters.keywords):
        reasons.append("keyword")

    return reasons


def _recency_score(published_at: datetime | None, ref: datetime | None) -> float:
    """최신성 [0,1]. ref(기준시점) 대비 최신일수록 1 에 가깝게."""
    if published_at is None or ref is None:
        return 0.0
    age_days = max(0, (ref - published_at).days)
    return 1.0 / (1.0 + age_days)


def compute_sort_score(issue: IssueView, ref: datetime | None) -> float:
    """정렬 점수 = 최신성 + 단계 가중 + 영향도(가중 합)."""
    recency = _recency_score(issue.published_at, ref)
    stage = STAGE_WEIGHT.get(issue.lifecycle_stage, 1.0) / _MAX_STAGE
    impact = min(len(issue.sectors) + len(issue.products), 6) / 6.0
    return round(W_RECENCY * recency + W_STAGE * stage + W_IMPACT * impact, 4)


def match_issues_for_group(
    group: Any,
    issues: list[IssueView],
    *,
    now: datetime | None = None,
) -> list[IssueView]:
    """그룹 filters 에 매칭되는 이슈를 골라 중요도순(내림차순)으로 반환한다.

    now: 최신성 기준 시점. 미지정 시 이슈들의 최신 published_at 을 기준으로 삼음(결정적).
    """
    filters = _coerce_filters(group)

    matched = [iss for iss in issues if match_reasons(filters, iss)]
    if not matched:
        return []

    ref = now
    if ref is None:
        dates = [iss.published_at for iss in matched if iss.published_at]
        ref = max(dates) if dates else None

    matched.sort(key=lambda iss: compute_sort_score(iss, ref), reverse=True)
    log.info(
        "그룹 매칭: 후보 %d건 중 %d건 매칭", len(issues), len(matched)
    )
    return matched
