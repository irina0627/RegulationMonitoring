"""데이터베이스 연결 계층.

`settings.DATABASE_URL` 로만 접속 정보를 얻는다(하드코딩 금지).
모든 모델은 `Base` 를 상속하고, 요청/작업 단위는 `get_session()` 으로 세션을 얻는다.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

if not settings.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 이 설정되지 않았습니다. .env(.env.example 복사)에 DATABASE_URL 을 채우세요."
    )

# pool_pre_ping: 끊긴 커넥션을 자동 감지·복구
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """모든 SQLAlchemy 모델의 공통 베이스."""


def get_session() -> Iterator[Session]:
    """세션을 열고 작업 후 반드시 닫는 의존성(FastAPI Depends 등).

    사용 예:
        @app.get(...)
        def handler(db: Session = Depends(get_session)): ...
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
