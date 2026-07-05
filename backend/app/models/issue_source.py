"""이슈-소스 엣지 (TRIGGERS / MENTIONS). 설계서 8장 issue_source."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IssueSource(Base):
    __tablename__ = "issue_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issue_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("issue.id"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)  # press_release|news
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation: Mapped[str] = mapped_column(Text, nullable=False)  # trigger|mention
