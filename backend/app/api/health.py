"""헬스체크 엔드포인트 (운영/모니터링용).

GET /api/health → 앱 상태 + DB 연결 여부.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine
from app.core.logging import get_logger

router = APIRouter(prefix="/api", tags=["health"])
log = get_logger(__name__)


@router.get("/health")
def health() -> dict:
    """앱 상태와 DB 연결 여부를 반환한다.

    DB 연결에 실패해도 200 을 반환하되 db="down" 으로 표시한다.
    (헬스 엔드포인트 자체는 항상 응답 가능해야 하므로)
    """
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 상태 보고용
        log.warning("DB 헬스체크 실패: %s", exc)
        db_status = "down"

    return {"status": "ok", "db": db_status}
