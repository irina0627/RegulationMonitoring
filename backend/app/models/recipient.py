"""그룹 수신자 (이메일 주소). 설계서 8장 recipient."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Recipient(Base):
    __tablename__ = "recipient"
    __table_args__ = (
        UniqueConstraint("group_id", "email", name="uq_recipient_group_email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("recipient_group.id")
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
