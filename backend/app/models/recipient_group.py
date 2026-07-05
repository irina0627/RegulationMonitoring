"""수신자 그룹 (부서·업권별 발송 단위). 설계서 8장 recipient_group."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecipientGroup(Base):
    __tablename__ = "recipient_group"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # 예: "리테일상품부"
    # {sectors:[],products:[],depts:[],keywords:[]} ↔ 이슈 엔터티 매칭
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
