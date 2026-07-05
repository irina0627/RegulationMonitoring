"""그룹별 이메일 다이제스트 구성·렌더 (설계서 10.3).

build_digest(group, since): M3 그룹 매칭으로 기간 내 신규/업데이트 이슈를 골라
그룹별 다이제스트 데이터를 만든다. render_digest 로 HTML(Jinja2) 렌더.

M3 노트 개선안 반영: 매칭·표시는 온톨로지 '등록' 엔터티만 사용(미등록 노이즈 제외).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.graph.grouping import IssueView, match_issues_for_group
from app.models.entity import Entity
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.models.press_release import PressRelease

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# 라이프사이클 stage_code → 한글 라벨(색만으로 의존하지 않도록 텍스트 병기)
STAGE_LABELS = {
    "PRE_NOTICE": "입법예고",
    "DECISION": "의결",
    "PROMULGATION": "공포",
    "SUB_LAW": "시행령·고시",
    "ENFORCEMENT": "시행",
    "FOLLOW_UP": "후속",
    "": "단계미정",
}
# 단계별 배경색(라벨과 병기, 접근성 위해 텍스트 필수)
STAGE_COLORS = {
    "PRE_NOTICE": "#6b7280",
    "DECISION": "#2563eb",
    "PROMULGATION": "#7c3aed",
    "SUB_LAW": "#0891b2",
    "ENFORCEMENT": "#059669",
    "FOLLOW_UP": "#d97706",
    "": "#9ca3af",
}
SOURCE_LABELS = {
    "press_release": "1차 · 금융위 보도자료",
    "news": "2차 · 언론",
}


@dataclass
class DigestItem:
    issue_id: int
    title: str
    summary: str
    why_it_matters: str
    stage_code: str
    stage_label: str
    stage_color: str
    sectors: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    source_label: str = ""
    source_url: str | None = None
    published_at: datetime | None = None
    is_update: bool = False  # 단계 변경으로 재포함된 이슈(업데이트 표시)


@dataclass
class DigestData:
    group_name: str
    count: int
    items: list[DigestItem] = field(default_factory=list)
    since: datetime | None = None


def _group_name(group: Any) -> str:
    if isinstance(group, dict):
        return group.get("name", "그룹")
    return getattr(group, "name", "그룹")


def _registered(e: Entity) -> bool:
    return not (e.meta and e.meta.get("unregistered"))


def _load_records(session: Session, since: datetime | None) -> list[dict]:
    """기간 내(신규/업데이트) 이슈를 표시·매칭용 레코드로 로드한다."""
    q = select(Issue)
    if since is not None:
        q = q.where(
            or_(Issue.last_updated_at >= since, Issue.first_seen_at >= since)
        )

    records: list[dict] = []
    for iss in session.execute(q).scalars():
        edges = session.execute(
            select(Entity)
            .join(IssueEntity, IssueEntity.entity_id == Entity.id)
            .where(IssueEntity.issue_id == iss.id)
        ).scalars().all()

        sectors = [e.canonical_name for e in edges if e.type == "sector" and _registered(e)]
        products = [e.canonical_name for e in edges if e.type == "product" and _registered(e)]
        depts = [e.canonical_name for e in edges if e.type in ("agency", "dept")]

        # trigger 소스(1차) 조회
        src = session.execute(
            select(IssueSource).where(
                IssueSource.issue_id == iss.id, IssueSource.relation == "trigger"
            )
        ).scalars().first()

        source_kind = "press_release"
        source_url: str | None = None
        pub = iss.first_seen_at
        if src is not None:
            source_kind = src.source_type
            if src.source_type == "press_release":
                pr = session.get(PressRelease, src.source_id)
                if pr is not None:
                    source_url = pr.source_url
                    pub = pr.published_at or pub

        records.append(
            {
                "id": iss.id,
                "title": iss.title,
                "summary": iss.summary or "",
                "why_it_matters": iss.why_it_matters or "",
                "stage_code": iss.lifecycle_stage or "",
                "sectors": sectors,
                "products": products,
                "depts": depts,
                "source_kind": source_kind,
                "source_url": source_url,
                "published_at": pub,
            }
        )
    return records


def _to_item(r: dict) -> DigestItem:
    stage = r["stage_code"]
    return DigestItem(
        issue_id=r["id"],
        title=r["title"],
        summary=r["summary"],
        why_it_matters=r["why_it_matters"],
        stage_code=stage,
        stage_label=STAGE_LABELS.get(stage, "단계미정"),
        stage_color=STAGE_COLORS.get(stage, STAGE_COLORS[""]),
        sectors=r["sectors"],
        products=r["products"],
        source_label=SOURCE_LABELS.get(r["source_kind"], r["source_kind"]),
        source_url=r["source_url"],
        published_at=r["published_at"],
    )


def build_digest(
    session: Session,
    group: Any,
    since: datetime | None = None,
    *,
    now: datetime | None = None,
) -> DigestData:
    """그룹 매칭으로 기간 내 이슈를 골라 다이제스트 데이터를 구성한다."""
    records = _load_records(session, since)
    views = [
        IssueView(
            id=r["id"], title=r["title"], summary=r["summary"],
            lifecycle_stage=r["stage_code"], sectors=r["sectors"],
            products=r["products"], depts=r["depts"], published_at=r["published_at"],
        )
        for r in records
    ]
    matched = match_issues_for_group(group, views, now=now)
    by_id = {r["id"]: r for r in records}
    items = [_to_item(by_id[v.id]) for v in matched]

    log.info("다이제스트 구성: 그룹=%s 이슈 %d건", _group_name(group), len(items))
    return DigestData(group_name=_group_name(group), count=len(items), items=items, since=since)


# --- 렌더 ----------------------------------------------------------------- #
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def _fmt_date(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


_env.filters["fmt_date"] = _fmt_date


def render_digest(data: DigestData) -> str:
    """다이제스트 데이터를 HTML 이메일 문자열로 렌더한다."""
    template = _env.get_template("digest.html.j2")
    return template.render(d=data)
