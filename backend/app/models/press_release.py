"""보도자료 (1차 소스). 설계서 8장 press_release."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PressRelease(Base):
    __tablename__ = "press_release"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fsc_post_id: Mapped[str | None] = mapped_column(Text)  # 게시판 게시물 식별자
    rss_guid: Mapped[str | None] = mapped_column(Text, unique=True)  # 중복 방지 키
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dept: Mapped[str | None] = mapped_column(Text)  # 담당부서
    source_url: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)  # 파싱된 본문
    attachments: Mapped[list | None] = mapped_column(JSONB)  # [{filename,type,url,parse_status}]
    parse_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    enrich_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
