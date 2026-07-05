"""법령 상세 (entity 보강). 설계서 8장 regulation_detail."""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RegulationDetail(Base):
    __tablename__ = "regulation_detail"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("entity.id"))
    law_id: Mapped[str | None] = mapped_column(Text)  # 법제처 법령ID
    enforce_date: Mapped[date | None] = mapped_column(Date)
    revision_history: Mapped[dict | None] = mapped_column(JSONB)
