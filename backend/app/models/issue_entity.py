"""이슈-엔터티 엣지 (BASED_ON / AFFECTS / HANDLED_BY). 설계서 8장 issue_entity."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IssueEntity(Base):
    __tablename__ = "issue_entity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issue_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("issue.id"))
    entity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("entity.id"))
    relation: Mapped[str] = mapped_column(Text, nullable=False)  # based_on|affects|handled_by
    weight: Mapped[Decimal] = mapped_column(Numeric, server_default=text("1.0"))
