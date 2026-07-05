"""이슈 클러스터링 (설계서 6.4).

같은 사안의 보도자료(+추후 기사)를 하나의 이슈로 묶는다.
방법: 제목+요약 임베딩 유사도 + 규칙(공통 법령/날짜 근접/키워드) 하이브리드.
자동 임계값 + 경계 사례 로깅. (표출용 시각화 없음)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.logging import get_logger
from app.graph.embeddings import Embedder, cosine, get_embedder

log = get_logger(__name__)

# --- 튜닝 상수 ------------------------------------------------------------- #
MERGE_THRESHOLD = 0.62  # 이 이상이면 같은 이슈로 병합
BOUNDARY_MARGIN = 0.05  # 임계값 ±이 범위는 경계 사례로 로깅(수동 검토 대상)
DATE_PROXIMITY_DAYS = 14  # 날짜 근접 판단 창
W_EMB = 0.7  # 임베딩 가중
W_RULE = 0.3  # 규칙 가중


@dataclass
class ClusterCandidate:
    """클러스터 비교 단위(보도자료 또는 기존 이슈)."""

    title: str
    summary: str = ""
    regulations: frozenset[str] = field(default_factory=frozenset)  # canonical 법령명
    published_at: datetime | None = None
    issue_id: int | None = None  # 기존 이슈면 그 id

    @property
    def text(self) -> str:
        return f"{self.title} {self.summary}".strip()


@dataclass
class ClusterResult:
    matched_issue_id: int | None  # 병합 대상 이슈 id(없으면 None=신규)
    score: float
    is_boundary: bool
    detail: dict


def _title_tokens(s: str) -> set[str]:
    return {w for w in re.split(r"[\s,·()「」“”\"']+", s or "") if len(w) >= 2}


def rule_score(a: ClusterCandidate, b: ClusterCandidate) -> tuple[float, dict]:
    """규칙 기반 유사도 [0,1] + 신호 상세."""
    score = 0.0
    signals: dict = {}

    shared_reg = a.regulations & b.regulations
    if shared_reg:
        score += 0.5
        signals["shared_reg"] = sorted(shared_reg)

    if a.published_at and b.published_at:
        days = abs((a.published_at - b.published_at).days)
        if days <= DATE_PROXIMITY_DAYS:
            score += 0.25 * (1 - days / DATE_PROXIMITY_DAYS)
            signals["date_days"] = days

    ta, tb = _title_tokens(a.title), _title_tokens(b.title)
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        if jac > 0:
            score += 0.25 * jac
            signals["title_jaccard"] = round(jac, 3)

    return min(1.0, score), signals


def find_matching_issue(
    candidate: ClusterCandidate,
    existing: list[ClusterCandidate],
    *,
    embedder: Embedder | None = None,
    threshold: float = MERGE_THRESHOLD,
) -> ClusterResult:
    """candidate 가 기존 이슈 중 하나와 같은 사안인지 판정한다.

    최고 점수 이슈가 임계값 이상이면 그 issue_id 를 반환(병합), 아니면 None(신규).
    임계값 경계(±BOUNDARY_MARGIN) 사례는 경고 로깅한다.
    """
    if not existing:
        return ClusterResult(None, 0.0, False, {})

    embedder = embedder or get_embedder()
    vecs = embedder.embed([candidate.text] + [e.text for e in existing])
    cv = vecs[0]

    best: ClusterCandidate | None = None
    best_score = -1.0
    best_detail: dict = {}
    for i, ex in enumerate(existing):
        emb = cosine(cv, vecs[i + 1])
        rule, sig = rule_score(candidate, ex)
        combined = W_EMB * emb + W_RULE * rule
        if combined > best_score:
            best_score = combined
            best = ex
            best_detail = {"emb": round(emb, 3), "rule": round(rule, 3), **sig}

    assert best is not None
    is_boundary = abs(best_score - threshold) <= BOUNDARY_MARGIN
    matched_id = best.issue_id if best_score >= threshold else None

    if is_boundary:
        log.warning(
            "클러스터 경계 사례(수동검토): score=%.3f (임계 %.2f) "
            "cand=%r ↔ best=%r detail=%s",
            best_score, threshold, candidate.title[:30], best.title[:30], best_detail,
        )
    else:
        log.info(
            "클러스터 판정: score=%.3f → %s (cand=%r)",
            best_score, "병합" if matched_id else "신규", candidate.title[:30],
        )

    return ClusterResult(matched_id, round(best_score, 3), is_boundary, best_detail)
