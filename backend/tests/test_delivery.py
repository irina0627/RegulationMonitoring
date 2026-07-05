"""발송 이력·중복 방지 + 빈 다이제스트 분기 테스트 (실제 PostgreSQL, 발송 mock)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.email import delivery as dlv
from app.email.delivery import (
    deliver_group_digest,
    filter_sendable,
    record_delivery,
)
from app.email.digest import DigestItem
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
    def __init__(self, ok: bool = True):
        self.calls: list = []
        self._ok = ok

    def send(self, to, subject, html) -> SendResult:
        self.calls.append({"to": to, "subject": subject, "html": html})
        return SendResult(ok=self._ok, accepted=list(to) if self._ok else [],
                          rejected=[] if self._ok else list(to),
                          error=None if self._ok else "boom")


def _item(issue_id: int, stage: str = "DECISION") -> DigestItem:
    return DigestItem(issue_id, "제목", "요약", "왜", stage, "라벨", "#000")


def _wipe(s):
    s.execute(delete(DeliveryLog))
    s.execute(delete(IssueEntity))
    s.execute(delete(IssueSource))
    s.execute(delete(Issue))
    s.execute(delete(Entity))
    s.execute(delete(Recipient))
    s.execute(delete(RecipientGroup))
    s.execute(delete(PressRelease).where(PressRelease.rss_guid.like("test-deliv-%")))


@pytest.fixture()
def base():
    """그룹 + 이슈 2개(FK 충족용)."""
    with SessionLocal() as s:
        _wipe(s)
        g = RecipientGroup(name="G", filters={"products": ["ELS"]}, active=True)
        s.add(g)
        s.flush()
        i1 = Issue(title="이슈1", lifecycle_stage="DECISION")
        i2 = Issue(title="이슈2", lifecycle_stage="DECISION")
        s.add_all([i1, i2])
        s.commit()
        ids = {"g": g.id, "i1": i1.id, "i2": i2.id}
        yield ids
        _wipe(s)
        s.commit()


# --- filter_sendable ------------------------------------------------------ #
def test_filter_excludes_already_sent(base) -> None:
    with SessionLocal() as s:
        # i1 을 어제 DECISION 으로 발송 기록
        record_delivery(s, base["g"], _item(base["i1"], "DECISION"), date(2026, 7, 4), "sent")
        s.commit()

        out = filter_sendable(s, base["g"],
                              [_item(base["i1"], "DECISION"), _item(base["i2"], "DECISION")],
                              DIGEST_DATE)
        # i1 은 이미 보냈고 단계 변화 없음 → 제외, i2 만 발송 대상
        assert [i.issue_id for i in out] == [base["i2"]]


def test_filter_reincludes_on_stage_change(base) -> None:
    with SessionLocal() as s:
        record_delivery(s, base["g"], _item(base["i1"], "DECISION"), date(2026, 7, 4), "sent")
        s.commit()
        out = filter_sendable(s, base["g"], [_item(base["i1"], "ENFORCEMENT")], DIGEST_DATE)
        assert len(out) == 1
        assert out[0].is_update is True  # 단계 변경 → 업데이트 재포함


def test_filter_excludes_sent_today(base) -> None:
    with SessionLocal() as s:
        record_delivery(s, base["g"], _item(base["i1"], "ENFORCEMENT"), DIGEST_DATE, "sent")
        s.commit()
        # 같은 날 이미 처리 → 단계가 달라도 재발송 안 함
        out = filter_sendable(s, base["g"], [_item(base["i1"], "PROMULGATION")], DIGEST_DATE)
        assert out == []


def test_record_delivery_is_idempotent(base) -> None:
    with SessionLocal() as s:
        record_delivery(s, base["g"], _item(base["i1"], "DECISION"), DIGEST_DATE, "sent")
        record_delivery(s, base["g"], _item(base["i1"], "DECISION"), DIGEST_DATE, "sent")
        s.commit()
        n = s.execute(
            select(func.count()).select_from(DeliveryLog).where(
                DeliveryLog.group_id == base["g"], DeliveryLog.issue_id == base["i1"]
            )
        ).scalar_one()
        assert n == 1  # (group, issue, date) 유니크


# --- 빈 다이제스트 분기 --------------------------------------------------- #
def test_empty_digest_skipped(base) -> None:
    # 매칭 이슈 없음(ELS 상품 태그 이슈 없음) → send_empty=False → 생략
    sender = FakeSender()
    with SessionLocal() as s:
        g = s.get(RecipientGroup, base["g"])
        res = deliver_group_digest(s, g, SINCE, DIGEST_DATE, sender=sender, send_empty=False)
    assert res.status == "skipped_empty"
    assert sender.calls == []  # 발송 안 함


def test_empty_digest_sent_when_configured(base) -> None:
    sender = FakeSender()
    with SessionLocal() as s:
        s.add(Recipient(group_id=base["g"], email="r@x.com", active=True))
        s.commit()
        g = s.get(RecipientGroup, base["g"])
        res = deliver_group_digest(s, g, SINCE, DIGEST_DATE, sender=sender, send_empty=True)
    assert res.status == "sent_empty"
    assert len(sender.calls) == 1
    assert "오늘 신규 없음" in sender.calls[0]["subject"]


# --- 전체 발송 + 중복 방지 ------------------------------------------------ #
@pytest.fixture()
def matching_issue(base):
    """ELS 상품 태그 + press_release trigger + 수신자."""
    with SessionLocal() as s:
        els = Entity(type="product", name="ELS", canonical_name="ELS")
        s.add(els)
        s.flush()
        pr = PressRelease(rss_guid="test-deliv-1", title="ELS", source_url="https://x/1",
                          published_at=datetime(2026, 7, 3, tzinfo=timezone.utc))
        s.add(pr)
        s.flush()
        # base 의 i1 을 ELS 이슈로 사용
        s.add(IssueEntity(issue_id=base["i1"], entity_id=els.id, relation="affects"))
        s.add(IssueSource(issue_id=base["i1"], source_type="press_release", source_id=pr.id, relation="trigger"))
        s.add(Recipient(group_id=base["g"], email="r@x.com", active=True))
        s.commit()
    return base


def test_full_send_and_no_duplicate(matching_issue) -> None:
    ids = matching_issue
    sender = FakeSender()
    with SessionLocal() as s:
        g = s.get(RecipientGroup, ids["g"])
        res1 = deliver_group_digest(s, g, SINCE, DIGEST_DATE, sender=sender)

    assert res1.status == "sent"
    assert res1.sent_issue_count == 1
    assert len(sender.calls) == 1
    assert "오늘의 핵심 1건" in sender.calls[0]["subject"]

    with SessionLocal() as s:
        logs = s.execute(select(DeliveryLog)).scalars().all()
        assert len(logs) == 1
        assert logs[0].status == "sent"

    # 같은 날 재실행 → 이미 보냄 → 빈 다이제스트 생략, 중복 발송 없음
    with SessionLocal() as s:
        g = s.get(RecipientGroup, ids["g"])
        res2 = deliver_group_digest(s, g, SINCE, DIGEST_DATE, sender=sender, send_empty=False)
    assert res2.status == "skipped_empty"
    assert len(sender.calls) == 1  # 추가 발송 없음
    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(DeliveryLog)).scalar_one()
        assert n == 1  # delivery_log 도 그대로


def test_failed_send_records_failed_status(matching_issue) -> None:
    ids = matching_issue
    sender = FakeSender(ok=False)  # 발송 실패
    with SessionLocal() as s:
        g = s.get(RecipientGroup, ids["g"])
        res = deliver_group_digest(s, g, SINCE, DIGEST_DATE, sender=sender)
    assert res.status == "sent"  # 시도는 함
    assert res.send_ok is False
    with SessionLocal() as s:
        log_row = s.execute(select(DeliveryLog)).scalars().one()
        assert log_row.status == "failed"
