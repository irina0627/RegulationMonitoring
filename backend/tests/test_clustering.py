"""이슈 클러스터링 테스트 (로컬 임베더, 네트워크 없음).

같은 사안 묶기 / 다른 사안 분리 / 경계 사례 로깅을 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.graph.clustering import (
    BOUNDARY_MARGIN,
    ClusterCandidate,
    find_matching_issue,
    rule_score,
)
from app.graph.embeddings import LocalEmbedder

EMB = LocalEmbedder()
D1 = datetime(2026, 7, 3, tzinfo=timezone.utc)
D2 = datetime(2026, 7, 5, tzinfo=timezone.utc)

PF_ISSUE = ClusterCandidate(
    title="부동산 프로젝트 금융(PF) 상황 점검회의 개최",
    summary="PF 익스포저가 감소하고 연착륙을 점검하였다.",
    regulations=frozenset({"한시적 금융규제완화조치"}),
    published_at=D1,
    issue_id=101,
)


def test_same_matter_is_merged() -> None:
    # 같은 사안(부동산 PF)·공통 법령·근접 날짜 → 병합
    cand = ClusterCandidate(
        title="부동산 프로젝트 금융(PF) 상황 추가 점검회의 개최",
        summary="부동산 PF 연착륙 상황을 재점검하였다.",
        regulations=frozenset({"한시적 금융규제완화조치"}),
        published_at=D2,
    )
    res = find_matching_issue(cand, [PF_ISSUE], embedder=EMB)
    assert res.matched_issue_id == 101
    assert res.score >= 0.62


def test_different_matter_is_separated() -> None:
    # 전혀 다른 사안(가상자산 시세조종) → 신규(None)
    cand = ClusterCandidate(
        title="가상자산시장 시세조종 혐의자 수사기관 고발",
        summary="시세조종 혐의자를 고발하기로 의결하였다.",
        regulations=frozenset(),
        published_at=D2,
    )
    res = find_matching_issue(cand, [PF_ISSUE], embedder=EMB)
    assert res.matched_issue_id is None
    assert res.score < 0.62


def test_empty_existing_returns_none() -> None:
    res = find_matching_issue(PF_ISSUE, [], embedder=EMB)
    assert res.matched_issue_id is None
    assert res.score == 0.0


def test_boundary_case_is_flagged() -> None:
    cand = ClusterCandidate(
        title="부동산 프로젝트 금융(PF) 상황 추가 점검",
        summary="PF 상황 점검",
        regulations=frozenset({"한시적 금융규제완화조치"}),
        published_at=D2,
    )
    # 실제 점수를 얻은 뒤 임계값을 그 점수로 잡으면 경계 사례가 된다(결정적)
    probe = find_matching_issue(cand, [PF_ISSUE], embedder=EMB, threshold=0.999)
    res = find_matching_issue(cand, [PF_ISSUE], embedder=EMB, threshold=probe.score)
    assert res.is_boundary is True
    assert abs(res.score - probe.score) <= BOUNDARY_MARGIN


def test_rule_score_signals() -> None:
    a = ClusterCandidate(title="부동산 PF 점검", regulations=frozenset({"L1"}), published_at=D1)
    b = ClusterCandidate(title="부동산 PF 점검 추가", regulations=frozenset({"L1"}), published_at=D2)
    score, sig = rule_score(a, b)
    assert "shared_reg" in sig  # 공통 법령
    assert "date_days" in sig  # 날짜 근접
    assert score > 0.5  # 공통 법령(0.5)만으로도 초과


def test_rule_score_no_signals() -> None:
    a = ClusterCandidate(title="가상자산 고발")
    b = ClusterCandidate(title="인터넷은행 대면업무")
    score, sig = rule_score(a, b)
    assert score == 0.0
    assert sig == {}
