"""운영·관리 엔드포인트 (헤드리스, 디버그/운영용).

사용자용 화면 없음. 내부 운영 트리거만 제공한다.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.core.scheduler import trigger_ingest_once
from app.email import recipients as rc
from app.email.delivery import run_daily_digest_guarded
from app.email.digest import build_digest, render_digest
from app.graph.moderation import merge_issues, split_issue
from app.models.recipient_group import RecipientGroup
from app.nlp.enrich import run_enrich_guarded

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = get_logger(__name__)


class MergeRequest(BaseModel):
    target_id: int  # 이 이슈로 병합


class SplitRequest(BaseModel):
    source_ids: list[int]  # 분리할 issue_source.id 목록
    new_title: str | None = None


class FiltersModel(BaseModel):
    sectors: list[str] = []
    products: list[str] = []
    depts: list[str] = []
    keywords: list[str] = []


class GroupCreate(BaseModel):
    name: str
    filters: FiltersModel = FiltersModel()
    active: bool = True


class GroupUpdate(BaseModel):
    name: str | None = None
    filters: FiltersModel | None = None
    active: bool | None = None


class RecipientCreate(BaseModel):
    group_id: int
    email: str
    name: str | None = None
    active: bool = True


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "detail": detail})


def _find_group(session, group: str):
    """group 파라미터(id 또는 name)로 RecipientGroup 조회."""
    grp = None
    if group.isdigit():
        grp = session.get(RecipientGroup, int(group))
    if grp is None:
        grp = session.execute(
            select(RecipientGroup).where(RecipientGroup.name == group)
        ).scalars().first()
    return grp


@router.post("/ingest/run")
def ingest_run():
    """즉시 1회 수집을 실행하고 결과 요약(신규/성공/실패 건수)을 반환한다.

    이미 수집이 진행 중이면 409(busy)로 응답한다(중복 실행 방지).
    """
    stats = trigger_ingest_once()
    if stats is None:
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "detail": "이미 수집이 진행 중입니다."},
        )
    return {"status": "ok", "result": stats}


@router.post("/enrich/run")
def enrich_run():
    """pending 보도자료를 LLM 으로 이슈/엔터티/엣지로 변환·적재한다.

    이미 enrich 가 진행 중이면 409(busy)로 응답한다(중복 실행 방지).
    """
    stats = run_enrich_guarded()
    if stats is None:
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "detail": "이미 enrich 가 진행 중입니다."},
        )
    return {"status": "ok", "result": stats}


@router.post("/issues/{issue_id}/merge")
def issue_merge(issue_id: int, req: MergeRequest):
    """이슈 {issue_id} 를 target_id 이슈로 병합한다(수동 보정)."""
    with SessionLocal() as s:
        try:
            result = merge_issues(s, source_id=issue_id, target_id=req.target_id)
        except LookupError as exc:
            s.rollback()
            return JSONResponse(status_code=404, content={"status": "error", "detail": str(exc)})
        except ValueError as exc:
            s.rollback()
            return JSONResponse(status_code=400, content={"status": "error", "detail": str(exc)})
        s.commit()
    return {"status": "ok", "result": result}


@router.post("/issues/{issue_id}/split")
def issue_split(issue_id: int, req: SplitRequest):
    """이슈 {issue_id} 의 일부 소스를 새 이슈로 분리한다(수동 보정)."""
    with SessionLocal() as s:
        try:
            result = split_issue(s, issue_id, req.source_ids, new_title=req.new_title)
        except LookupError as exc:
            s.rollback()
            return JSONResponse(status_code=404, content={"status": "error", "detail": str(exc)})
        except ValueError as exc:
            s.rollback()
            return JSONResponse(status_code=400, content={"status": "error", "detail": str(exc)})
        s.commit()
    return {"status": "ok", "result": result}


# --- 다이제스트 ----------------------------------------------------------- #
@router.post("/digest/run")
def digest_run(dry_run: bool = False):
    """활성 그룹 전체에 다이제스트 발송. ?dry_run=true 면 발송 없이 결과만."""
    result = run_daily_digest_guarded(dry_run=dry_run)
    if result is None:
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "detail": "이미 다이제스트가 진행 중입니다."},
        )
    return {"status": "ok", "result": result}


@router.get("/digest/preview", response_class=HTMLResponse)
def digest_preview(group: str):
    """발송 없이 그룹 다이제스트 HTML 미리보기(group=id 또는 name)."""
    with SessionLocal() as s:
        grp = _find_group(s, group)
        if grp is None:
            return HTMLResponse(f"<p>그룹을 찾을 수 없습니다: {group}</p>", status_code=404)
        data = build_digest(s, grp, since=None)
        html = render_digest(data)
    return HTMLResponse(html)


# --- 수신자 그룹 관리 ----------------------------------------------------- #
@router.post("/recipients/seed")
def recipients_seed():
    """config/recipients.yaml 을 recipient_group/recipient 로 멱등 적재한다."""
    with SessionLocal() as s:
        try:
            stats = rc.load_seed(s)
        except FileNotFoundError as exc:
            return _err(404, f"시드 파일 없음: {exc}")
    return {"status": "ok", "result": stats}


@router.get("/groups")
def groups_list():
    with SessionLocal() as s:
        return {"status": "ok", "groups": rc.list_groups(s)}


@router.post("/groups")
def groups_create(req: GroupCreate):
    with SessionLocal() as s:
        grp = rc.create_group(s, req.name, req.filters.model_dump(), req.active)
    return {"status": "ok", "group": grp}


@router.put("/groups/{group_id}")
def groups_update(group_id: int, req: GroupUpdate):
    with SessionLocal() as s:
        try:
            grp = rc.update_group(
                s, group_id,
                name=req.name,
                filters=req.filters.model_dump() if req.filters is not None else None,
                active=req.active,
            )
        except LookupError as exc:
            s.rollback()
            return _err(404, str(exc))
    return {"status": "ok", "group": grp}


@router.delete("/groups/{group_id}")
def groups_delete(group_id: int):
    with SessionLocal() as s:
        try:
            rc.delete_group(s, group_id)
        except LookupError as exc:
            s.rollback()
            return _err(404, str(exc))
    return {"status": "ok"}


@router.get("/recipients")
def recipients_list(group_id: int | None = None):
    with SessionLocal() as s:
        return {"status": "ok", "recipients": rc.list_recipients(s, group_id)}


@router.post("/recipients")
def recipients_create(req: RecipientCreate):
    with SessionLocal() as s:
        try:
            r = rc.add_recipient(s, req.group_id, req.email, req.name, req.active)
        except LookupError as exc:
            s.rollback()
            return _err(404, str(exc))
        except ValueError as exc:
            s.rollback()
            return _err(409, str(exc))
    return {"status": "ok", "recipient": r}


@router.delete("/recipients/{recipient_id}")
def recipients_delete(recipient_id: int):
    with SessionLocal() as s:
        try:
            rc.delete_recipient(s, recipient_id)
        except LookupError as exc:
            s.rollback()
            return _err(404, str(exc))
    return {"status": "ok"}
