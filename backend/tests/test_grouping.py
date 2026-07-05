"""그룹 ↔ 이슈 매칭 테스트 (설계서 10.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.graph.grouping import (
    GroupFilters,
    IssueView,
    compute_sort_score,
    match_issues_for_group,
    match_reasons,
)

D = lambda d: datetime(2026, 7, d, tzinfo=timezone.utc)  # noqa: E731

# --- 샘플 이슈 ------------------------------------------------------------ #
ELS_ISSUE = IssueView(
    id=1, title="ELS 판매규제 강화", summary="주가연계증권 판매비중 규제",
    lifecycle_stage="DECISION", sectors=["증권"], products=["ELS"], published_at=D(3),
)
CRYPTO_ISSUE = IssueView(
    id=2, title="가상자산 시세조종 혐의자 수사기관 고발", summary="시세조종 단속 강화",
    lifecycle_stage="DECISION", sectors=["가상자산"], products=[], published_at=D(2),
)
INSPECTION_ISSUE = IssueView(
    id=3, title="개인채무자보호 감독규정 검사 계획", summary="현장 검사 및 제재 예정",
    lifecycle_stage="ENFORCEMENT", sectors=["은행"], depts=["서민금융과"], published_at=D(4),
)
BANK_ISSUE = IssueView(
    id=4, title="인터넷전문은행 대면업무 조정", summary="은행 업무범위 조정",
    lifecycle_stage="DECISION", sectors=["은행"], published_at=D(1),
)

ALL = [ELS_ISSUE, CRYPTO_ISSUE, INSPECTION_ISSUE, BANK_ISSUE]


# --- 파생업권 그룹: ELS/DLS 상품 이슈만 --------------------------------------- #
def test_derivatives_group_matches_only_els_dls() -> None:
    group = {"products": ["ELS", "DLS"]}
    out = match_issues_for_group(group, ALL)
    assert [i.id for i in out] == [1]  # ELS 이슈만


# --- 컴플라이언스 그룹: 제재·검사·고발 키워드 -------------------------------- #
def test_compliance_group_matches_enforcement_keywords() -> None:
    group = {"keywords": ["제재", "검사", "고발"]}
    out = match_issues_for_group(group, ALL)
    ids = {i.id for i in out}
    assert ids == {2, 3}  # 고발(2), 검사·제재(3)
    assert 1 not in ids and 4 not in ids


# --- 업권 그룹 + 정규화 --------------------------------------------------- #
def test_sector_group_with_normalization() -> None:
    # filters 에 동의어(금융투자업) → 이슈 sector '증권' 과 매칭돼야
    group = {"sectors": ["금융투자업"]}
    out = match_issues_for_group(group, ALL)
    assert [i.id for i in out] == [1]


def test_dept_group_matching() -> None:
    group = {"depts": ["서민금융과"]}
    out = match_issues_for_group(group, ALL)
    assert [i.id for i in out] == [3]


def test_no_match_returns_empty() -> None:
    group = {"sectors": ["보험"], "products": ["펀드"]}
    assert match_issues_for_group(group, ALL) == []


# --- 정렬: 중요도순 ------------------------------------------------------- #
def test_sorted_by_importance() -> None:
    # 은행 그룹: 이슈 3(ENFORCEMENT, 최신 7/4), 4(DECISION, 7/1) 매칭 → 3 이 먼저
    group = {"sectors": ["은행"]}
    out = match_issues_for_group(group, ALL)
    assert [i.id for i in out] == [3, 4]
    ref = D(4)
    assert compute_sort_score(out[0], ref) > compute_sort_score(out[1], ref)


def test_match_reasons_multiple() -> None:
    filters = GroupFilters(sectors=["증권"], products=["ELS"])
    reasons = match_reasons(filters, ELS_ISSUE)
    assert set(reasons) == {"sector", "product"}


def test_accepts_group_model_like_object() -> None:
    class G:  # recipient_group 유사(.filters)
        filters = {"products": ["ELS"]}

    out = match_issues_for_group(G(), ALL)
    assert [i.id for i in out] == [1]
