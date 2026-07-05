"""일일 다이제스트 실행기 테스트 (dry_run vs 실제, 발송 mock)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.email.delivery import run_daily_digest
from app.email.sender import SendResult
from app.models.delivery_log import DeliveryLog
from app.models.entity import Entity
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.models.press_release import PressRelease
from app.models.recipient import Recipient
from app.models.recipient_group import RecipientGroup

DIGEST_DATE = date(2026, 7, 5)
SINCE = datetime(2020, 1, 1, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self):
        self.calls = []

    def send(self, to, subject, html) -> SendResult:
        self.calls.append({"to": to, "subject": subject})
        return SendResult(ok=True, accepted=list(to))


def _wipe(s):
    s.execute(delete(DeliveryLog))
    s.execute(delete(IssueEntity))
    s.execute(delete(IssueSource))
    s.execute(delete(Issue))
    s.execute(delete(Entity))
    s.execute(delete(Recipient))
    s.execute(delete(RecipientGroup))
    s.execute(delete(PressRelease).where(PressRelease.rss_guid.like("test-run-%")))


@pytest.fixture()
def one_group_one_issue():
    with SessionLocal() as s:
        _wipe(s)
        g = RecipientGroup(name="파생업권", filters={"products": ["ELS"]}, active=True)
        s.add(g)
        s.flush()
        els = Entity(type="product", name="ELS", canonical_name="ELS")
        s.add(els)
        s.flush()
        pr = PressRelease(rss_guid="test-run-1", title="ELS", source_url="https://x/1",
                          published_at=datetime(2026, 7, 3, tzinfo=timezone.utc))
        s.add(pr)
        s.flush()
        iss = Issue(title="ELS 규제", summary="요약", lifecycle_stage="DECISION")
        s.add(iss)
        s.flush()
        s.add(IssueEntity(issue_id=iss.id, entity_id=els.id, relation="affects"))
        s.add(IssueSource(issue_id=iss.id, source_type="press_release", source_id=pr.id, relation="trigger"))
        s.add(Recipient(group_id=g.id, email="r@x.com", active=True))
        s.commit()
        yield
        _wipe(s)
        s.commit()


def _delivery_count():
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(DeliveryLog)).scalar_one()


def test_dry_run_no_send_no_log(one_group_one_issue) -> None:
    sender = FakeSender()
    result = run_daily_digest(
        digest_date=DIGEST_DATE, since=SINCE, dry_run=True, sender=sender
    )
    assert result["dry_run"] is True
    assert result["totals"]["groups"] == 1
    assert result["totals"]["issues"] == 1
    assert sender.calls == []  # 발송 안 함
    assert _delivery_count() == 0  # 기록 안 함


def test_actual_run_sends_and_logs(one_group_one_issue) -> None:
    sender = FakeSender()
    result = run_daily_digest(
        digest_date=DIGEST_DATE, since=SINCE, dry_run=False, sender=sender
    )
    assert result["dry_run"] is False
    assert result["totals"]["issues"] == 1
    assert result["totals"]["recipients"] == 1
    assert len(sender.calls) == 1
    assert _delivery_count() == 1

    # 재실행(같은 날) → 중복 발송 없음
    sender2 = FakeSender()
    result2 = run_daily_digest(
        digest_date=DIGEST_DATE, since=SINCE, dry_run=False, sender=sender2
    )
    assert result2["totals"]["issues"] == 0  # 이미 보냄
    assert sender2.calls == []
    assert _delivery_count() == 1  # 그대로


def test_run_with_no_active_groups() -> None:
    with SessionLocal() as s:
        _wipe(s)
        s.commit()
    result = run_daily_digest(digest_date=DIGEST_DATE, since=SINCE, dry_run=True, sender=FakeSender())
    assert result["totals"]["groups"] == 0
