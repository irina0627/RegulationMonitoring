"""엔터티 (법령/상품/업권/기관/부서). 설계서 8장 entity."""

from __future__ import annotations

from sqlalchemy import BigInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Entity(Base):
    __tablename__ = "entity"
    __table_args__ = (
        UniqueConstraint("type", "canonical_name", name="uq_entity_type_canonical"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # regulation|product|sector|agency|dept
    name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(Text)  # 정규화 명칭
    # DB 컬럼명은 설계서대로 "metadata" 이나, Base.metadata 와 충돌하므로 속성명은 meta 로 매핑
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB)
