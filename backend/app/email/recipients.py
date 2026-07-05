"""수신자 그룹·수신자 관리 (설계서 8·10.2).

- recipients.yaml 시드를 recipient_group/recipient 테이블에 멱등 적재.
- 그룹·수신자 CRUD 서비스 함수(admin 엔드포인트가 호출).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.recipient import Recipient
from app.models.recipient_group import RecipientGroup

log = get_logger(__name__)

# backend/config/recipients.yaml
DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "config" / "recipients.yaml"

_FILTER_KEYS = ("sectors", "products", "depts", "keywords")


def _normalize_filters(filters: dict | None) -> dict:
    filters = filters or {}
    return {k: list(filters.get(k, []) or []) for k in _FILTER_KEYS}


# --- 직렬화 --------------------------------------------------------------- #
def group_to_dict(session: Session, g: RecipientGroup) -> dict:
    count = session.execute(
        select(func.count()).select_from(Recipient).where(Recipient.group_id == g.id)
    ).scalar_one()
    return {
        "id": g.id,
        "name": g.name,
        "filters": g.filters,
        "active": g.active,
        "recipient_count": count,
    }


def recipient_to_dict(r: Recipient) -> dict:
    return {
        "id": r.id,
        "group_id": r.group_id,
        "email": r.email,
        "name": r.name,
        "active": r.active,
    }


# --- 시드 로더 ------------------------------------------------------------ #
def load_seed(session: Session, path: str | Path | None = None) -> dict:
    """recipients.yaml → recipient_group/recipient 멱등 적재.

    그룹은 name 으로 매칭(있으면 갱신). 수신자는 (group, email)로 upsert 하고,
    yaml 에 없는 수신자는 제거해 yaml 을 소스오브트루스로 동기화한다.
    """
    path = Path(path) if path else DEFAULT_SEED_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    groups = data.get("groups", []) or []

    stats = {"groups": 0, "recipients_upserted": 0, "recipients_removed": 0}
    for g in groups:
        name = g["name"]
        filters = _normalize_filters(g.get("filters"))
        active = bool(g.get("active", True))

        grp = session.execute(
            select(RecipientGroup).where(RecipientGroup.name == name)
        ).scalars().first()
        if grp is None:
            grp = RecipientGroup(name=name, filters=filters, active=active)
            session.add(grp)
            session.flush()
        else:
            grp.filters = filters
            grp.active = active
        stats["groups"] += 1

        seed_recips = g.get("recipients") or []
        seed_emails = {r["email"] for r in seed_recips}

        # yaml 에 없는 기존 수신자 제거(동기화)
        for r in session.execute(
            select(Recipient).where(Recipient.group_id == grp.id)
        ).scalars():
            if r.email not in seed_emails:
                session.delete(r)
                stats["recipients_removed"] += 1

        # 수신자 upsert (group_id, email)
        for r in seed_recips:
            stmt = pg_insert(Recipient).values(
                group_id=grp.id,
                email=r["email"],
                name=r.get("name"),
                active=bool(r.get("active", True)),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id", "email"],  # uq_recipient_group_email
                set_={"name": stmt.excluded.name, "active": stmt.excluded.active},
            )
            session.execute(stmt)
            stats["recipients_upserted"] += 1

    session.commit()
    log.info("수신자 시드 로딩: %s", stats)
    return stats


# --- 그룹 CRUD ------------------------------------------------------------ #
def list_groups(session: Session) -> list[dict]:
    groups = session.execute(select(RecipientGroup).order_by(RecipientGroup.id)).scalars().all()
    return [group_to_dict(session, g) for g in groups]


def create_group(
    session: Session, name: str, filters: dict | None = None, active: bool = True
) -> dict:
    grp = RecipientGroup(name=name, filters=_normalize_filters(filters), active=active)
    session.add(grp)
    session.commit()
    return group_to_dict(session, grp)


def update_group(
    session: Session,
    group_id: int,
    *,
    name: str | None = None,
    filters: dict | None = None,
    active: bool | None = None,
) -> dict:
    grp = session.get(RecipientGroup, group_id)
    if grp is None:
        raise LookupError(f"그룹 {group_id} 없음")
    if name is not None:
        grp.name = name
    if filters is not None:
        grp.filters = _normalize_filters(filters)
    if active is not None:
        grp.active = active
    session.commit()
    return group_to_dict(session, grp)


def delete_group(session: Session, group_id: int) -> None:
    grp = session.get(RecipientGroup, group_id)
    if grp is None:
        raise LookupError(f"그룹 {group_id} 없음")
    # 수신자 먼저 삭제(FK)
    for r in session.execute(
        select(Recipient).where(Recipient.group_id == group_id)
    ).scalars():
        session.delete(r)
    session.flush()
    session.delete(grp)
    session.commit()


# --- 수신자 CRUD ---------------------------------------------------------- #
def list_recipients(session: Session, group_id: int | None = None) -> list[dict]:
    q = select(Recipient).order_by(Recipient.id)
    if group_id is not None:
        q = q.where(Recipient.group_id == group_id)
    return [recipient_to_dict(r) for r in session.execute(q).scalars()]


def add_recipient(
    session: Session,
    group_id: int,
    email: str,
    name: str | None = None,
    active: bool = True,
) -> dict:
    if session.get(RecipientGroup, group_id) is None:
        raise LookupError(f"그룹 {group_id} 없음")
    dup = session.execute(
        select(Recipient).where(
            Recipient.group_id == group_id, Recipient.email == email
        )
    ).scalars().first()
    if dup is not None:
        raise ValueError(f"이미 존재하는 수신자: {email}")
    r = Recipient(group_id=group_id, email=email, name=name, active=active)
    session.add(r)
    session.commit()
    return recipient_to_dict(r)


def delete_recipient(session: Session, recipient_id: int) -> None:
    r = session.get(Recipient, recipient_id)
    if r is None:
        raise LookupError(f"수신자 {recipient_id} 없음")
    session.delete(r)
    session.commit()
