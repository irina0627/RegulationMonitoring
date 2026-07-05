"""발송 이력 (중복 발송 방지). 설계서 8장 delivery_log."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DeliveryLog(Base):
    __tablename__ = "delivery_log"
    # 같은 이슈를 같은 그룹에 같은 날 두 번 보내지 않음
    __table_args__ = (
        UniqueConstraint(
            "group_id", "issue_id", "digest_date", name="uq_delivery_group_issue_date"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("recipient_group.id")
    )
    issue_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("issue.id"))
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'sent'"))  # sent|failed
    # 발송 당시 라이프사이클 단계 — 이후 단계 변경 감지(업데이트 재포함)용
    lifecycle_stage: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
