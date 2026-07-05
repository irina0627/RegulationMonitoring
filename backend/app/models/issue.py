"""규제 이슈 (허브 노드). 설계서 8장 issue."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Issue(Base):
    __tablename__ = "issue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)  # LLM 한 줄 요약
    why_it_matters: Mapped[str | None] = mapped_column(Text)  # LLM "왜 중요한가"
    lifecycle_stage: Mapped[str | None] = mapped_column(Text)  # stage_code
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    importance_score: Mapped[Decimal] = mapped_column(Numeric, server_default=text("0"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
