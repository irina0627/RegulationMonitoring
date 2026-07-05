"""FastAPI 애플리케이션 진입점 (헤드리스 운영용).

사용자용 웹 화면은 없다. 운영·관리·헬스체크용 HTTP 엔드포인트만 노출한다.
시작 시 수집 스케줄러를 기동하고, 종료 시 정리한다.

실행:
    cd backend && PYTHONPATH=. uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, health
from app.core.logging import get_logger, setup_logging
from app.core.scheduler import shutdown_scheduler, start_scheduler

setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명주기: 시작 시 스케줄러 기동, 종료 시 정리."""
    start_scheduler()
    log.info("FastAPI 앱 시작")
    try:
        yield
    finally:
        shutdown_scheduler()
        log.info("FastAPI 앱 종료")


app = FastAPI(
    title="금융규제 실시간 모니터링 시스템",
    description="헤드리스 운영용 API (사용자 웹 화면 없음). 표출은 이메일 다이제스트.",
    version="0.1.0",
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(health.router)
app.include_router(admin.router)
