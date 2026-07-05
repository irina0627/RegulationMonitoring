"""발송 이력·중복 방지 + 다이제스트 발송 실행 (설계서 10.5·10.6).

- 발송 전: delivery_log 로 이미 보낸 이슈 제외. 단, 라이프사이클 단계가 바뀐 이슈는
  "업데이트" 표시로 1회 재포함.
- 발송 후: delivery_log 에 (group, issue, digest_date) 기록(status sent/failed, 당시 단계).
- 빈 다이제스트: SEND_EMPTY_DIGEST 에 따라 생략 또는 "오늘 신규 없음" 메일.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.email.digest import DigestData, DigestItem, build_digest, render_digest
from app.email.recipients import list_recipients
from app.email.sender import EmailSender, SendResult, get_email_sender
from app.models.delivery_log import DeliveryLog
from app.models.recipient_group import RecipientGroup

log = get_logger(__name__)


@dataclass
class DeliveryResult:
    group_name: str
    status: str  # sent | sent_empty | skipped_empty | no_recipients
    sent_issue_count: int = 0
    update_count: int = 0
    recipients: int = 0
    send_ok: bool = True
    error: str | None = None
    logged_issue_ids: list[int] = field(default_factory=list)


def _last_sent(session: Session, group_id: int, issue_id: int) -> DeliveryLog | None:
    """(group, issue) 의 가장 최근 sent 기록."""
    return session.execute(
        select(DeliveryLog)
        .where(
            DeliveryLog.group_id == group_id,
            DeliveryLog.issue_id == issue_id,
            DeliveryLog.status == "sent",
        )
        .order_by(DeliveryLog.sent_at.desc())
    ).scalars().first()


def _sent_today(session: Session, group_id: int, issue_id: int, digest_date: date) -> bool:
    return session.execute(
        select(DeliveryLog.id).where(
            DeliveryLog.group_id == group_id,
            DeliveryLog.issue_id == issue_id,
            DeliveryLog.digest_date == digest_date,
        )
    ).first() is not None


def filter_sendable(
    session: Session, group_id: int, items: list[DigestItem], digest_date: date
) -> list[DigestItem]:
    """이미 보낸 이슈를 제외하고, 단계 변경분은 업데이트로 표시해 반환한다."""
    result: list[DigestItem] = []
    for item in items:
        if _sent_today(session, group_id, item.issue_id, digest_date):
            continue  # 같은 날 이미 처리됨(중복 방지)
        prior = _last_sent(session, group_id, item.issue_id)
        if prior is None:
            item.is_update = False
            result.append(item)
        elif (prior.lifecycle_stage or "") != (item.stage_code or ""):
            item.is_update = True  # 단계 변경 → 1회 재포함
            result.append(item)
        # else: 이미 보냈고 단계 변화 없음 → 제외
    return result


def record_delivery(
    session: Session, group_id: int, item: DigestItem, digest_date: date, status: str
) -> None:
    """delivery_log 기록(멱등: (group, issue, digest_date) 유니크 upsert)."""
    stmt = pg_insert(DeliveryLog).values(
        group_id=group_id,
        issue_id=item.issue_id,
        digest_date=digest_date,
        status=status,
        lifecycle_stage=item.stage_code or None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["group_id", "issue_id", "digest_date"],  # uq_delivery_group_issue_date
        set_={"status": stmt.excluded.status, "lifecycle_stage": stmt.excluded.lifecycle_stage},
    )
    session.execute(stmt)


def deliver_group_digest(
    session: Session,
    group,
    since,
    digest_date: date,
    *,
    sender: EmailSender | None = None,
    send_empty: bool | None = None,
    dry_run: bool = False,
    now=None,
) -> DeliveryResult:
    """한 그룹의 다이제스트를 구성→중복제외→발송→이력기록 한다.

    dry_run=True 면 발송·기록 없이 결과 요약만 반환한다.
    """
    sender = sender or get_email_sender()
    send_empty = settings.SEND_EMPTY_DIGEST if send_empty is None else send_empty
    group_id = getattr(group, "id", None) or (group.get("id") if isinstance(group, dict) else None)
    group_name = getattr(group, "name", None) or (group.get("name") if isinstance(group, dict) else "그룹")

    # 수신자
    recips = [r["email"] for r in list_recipients(session, group_id) if r["active"]] if group_id else []

    # 다이제스트 구성 + 중복 제외
    data = build_digest(session, group, since, now=now)
    sendable = filter_sendable(session, group_id, data.items, digest_date) if group_id else data.items
    updates = sum(1 for i in sendable if i.is_update)

    # dry_run: 발송·기록 없이 요약만
    if dry_run:
        return DeliveryResult(
            group_name, "dry_run", sent_issue_count=len(sendable),
            update_count=updates, recipients=len(recips),
            logged_issue_ids=[i.issue_id for i in sendable],
        )

    # 빈 다이제스트 분기
    if not sendable:
        if not send_empty:
            log.info("빈 다이제스트 생략: group=%s", group_name)
            return DeliveryResult(group_name, "skipped_empty", recipients=len(recips))
        empty = DigestData(group_name=group_name, count=0, items=[], since=since)
        html = render_digest(empty)
        res = _send(sender, recips, f"[규제 다이제스트] {group_name} — 오늘 신규 없음", html)
        return DeliveryResult(group_name, "sent_empty", recipients=len(recips),
                              send_ok=res.ok, error=res.error)

    if not recips:
        log.warning("수신자 없음 — 발송 생략: group=%s", group_name)
        return DeliveryResult(group_name, "no_recipients", sent_issue_count=len(sendable))

    # 렌더 + 발송
    data.items = sendable
    data.count = len(sendable)
    html = render_digest(data)
    subject = f"[규제 다이제스트] {group_name} — 오늘의 핵심 {len(sendable)}건"
    res = _send(sender, recips, subject, html)

    # 이력 기록
    status = "sent" if res.ok else "failed"
    for item in sendable:
        record_delivery(session, group_id, item, digest_date, status)
    session.commit()

    updates = sum(1 for i in sendable if i.is_update)
    log.info("다이제스트 발송: group=%s 이슈 %d건(업데이트 %d) 수신 %d명 status=%s",
             group_name, len(sendable), updates, len(recips), status)
    return DeliveryResult(
        group_name, "sent", sent_issue_count=len(sendable), update_count=updates,
        recipients=len(recips), send_ok=res.ok, error=res.error,
        logged_issue_ids=[i.issue_id for i in sendable],
    )


def _send(sender: EmailSender, to: list[str], subject: str, html: str) -> SendResult:
    return sender.send(to, subject, html)


# --- 전체 그룹 일일 실행 -------------------------------------------------- #
def run_daily_digest(
    *,
    session_factory=SessionLocal,
    digest_date: date | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    sender: EmailSender | None = None,
    now=None,
) -> dict:
    """활성 그룹 전체를 순회하며 다이제스트를 발송(또는 dry_run)한다.

    since=None 이면 전체 이슈를 후보로 두되 delivery_log 중복 제외로 재발송을 막는다.
    """
    sender = sender or get_email_sender()
    digest_date = digest_date or datetime.now().date()

    results: list[DeliveryResult] = []
    with session_factory() as session:
        groups = session.execute(
            select(RecipientGroup).where(RecipientGroup.active.is_(True)).order_by(RecipientGroup.id)
        ).scalars().all()
        for g in groups:
            results.append(
                deliver_group_digest(
                    session, g, since, digest_date,
                    sender=sender, dry_run=dry_run, now=now,
                )
            )

    totals = {
        "groups": len(results),
        "sent": sum(1 for r in results if r.status in ("sent", "sent_empty")),
        "skipped_empty": sum(1 for r in results if r.status == "skipped_empty"),
        "no_recipients": sum(1 for r in results if r.status == "no_recipients"),
        "issues": sum(r.sent_issue_count for r in results),
        "updates": sum(r.update_count for r in results),
        "recipients": sum(r.recipients for r in results),
        "failures": sum(1 for r in results if r.send_ok is False),
    }
    log.info(
        "일일 다이제스트%s: 그룹 %d, 발송 %d, 빈생략 %d, 이슈 %d(업데이트 %d), 수신자 %d, 실패 %d",
        " (dry_run)" if dry_run else "", totals["groups"], totals["sent"],
        totals["skipped_empty"], totals["issues"], totals["updates"],
        totals["recipients"], totals["failures"],
    )
    return {
        "digest_date": str(digest_date),
        "dry_run": dry_run,
        "totals": totals,
        "groups": [asdict(r) for r in results],
    }


_daily_lock = threading.Lock()


def run_daily_digest_guarded(**kwargs) -> dict | None:
    """일일 다이제스트를 1회 실행하되 이미 진행 중이면 None(busy)."""
    if not _daily_lock.acquire(blocking=False):
        log.info("이전 다이제스트 진행 중 — 이번 실행 건너뜀(busy)")
        return None
    try:
        return run_daily_digest(**kwargs)
    except Exception:  # noqa: BLE001
        log.exception("일일 다이제스트 실행 중 예외")
        return None
    finally:
        _daily_lock.release()
