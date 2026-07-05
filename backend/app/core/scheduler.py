"""수집 스케줄러 (APScheduler).

POLL_INTERVAL_MIN(기본 10분)마다 run_ingest() 를 실행한다.
FastAPI lifespan 에서 start_scheduler()/shutdown_scheduler() 로 기동·정리한다.

중복 실행 방지:
- 스케줄 잡은 max_instances=1, coalesce=True.
- 스케줄 실행과 수동 트리거가 겹치지 않도록 프로세스 레벨 Lock 을 공유한다.
  이미 진행 중이면 이번 실행은 건너뛴다(busy).
"""

from __future__ import annotations

import threading
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.collectors.ingest import run_ingest
from app.core.config import settings
from app.core.logging import get_logger
from app.email.delivery import run_daily_digest_guarded

log = get_logger(__name__)

_JOB_ID = "ingest"
_DIGEST_JOB_ID = "daily_digest"
_KST = ZoneInfo("Asia/Seoul")
_scheduler: BackgroundScheduler | None = None
# 스케줄/수동 수집이 겹치지 않게 하는 공유 락
_ingest_lock = threading.Lock()


def run_daily_digest_job() -> None:
    """스케줄 잡: 활성 그룹 전체에 다이제스트 발송(중복 실행 방지는 delivery 락)."""
    res = run_daily_digest_guarded()
    if res is None:
        log.info("일일 다이제스트가 이미 진행 중 — 이번 실행 건너뜀")


def run_ingest_guarded() -> dict | None:
    """수집을 1회 실행하되, 이미 진행 중이면 건너뛴다.

    반환: 실행됐으면 통계 dict, 이미 진행 중이면 None.
    """
    if not _ingest_lock.acquire(blocking=False):
        log.info("이전 수집이 진행 중 — 이번 실행 건너뜀(busy)")
        return None
    try:
        return run_ingest()
    except Exception:  # noqa: BLE001 - 스케줄 잡이 죽지 않도록
        log.exception("수집 실행 중 예외")
        return None
    finally:
        _ingest_lock.release()


def start_scheduler() -> BackgroundScheduler:
    """스케줄러를 기동한다(멱등). POLL_INTERVAL_MIN 간격 잡 등록."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    interval = max(1, int(settings.POLL_INTERVAL_MIN))
    scheduler = BackgroundScheduler(timezone=ZoneInfo("UTC"))
    scheduler.add_job(
        run_ingest_guarded,
        trigger="interval",
        minutes=interval,
        id=_JOB_ID,
        max_instances=1,  # 동일 잡 동시 실행 금지
        coalesce=True,  # 밀린 실행은 1회로 합침
        replace_existing=True,
    )
    # 매일 DIGEST_SEND_HOUR 시(KST)에 다이제스트 발송
    digest_hour = int(settings.DIGEST_SEND_HOUR)
    scheduler.add_job(
        run_daily_digest_job,
        trigger=CronTrigger(hour=digest_hour, minute=0, timezone=_KST),
        id=_DIGEST_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler

    job = scheduler.get_job(_JOB_ID)
    digest_job = scheduler.get_job(_DIGEST_JOB_ID)
    log.info(
        "스케줄러 기동: 수집 %d분 간격(다음 %s) · 다이제스트 매일 %02d:00 KST(다음 %s)",
        interval, getattr(job, "next_run_time", None),
        digest_hour, getattr(digest_job, "next_run_time", None),
    )
    return scheduler


def shutdown_scheduler() -> None:
    """스케줄러를 정리한다(멱등)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("스케줄러 종료")
    _scheduler = None


def trigger_ingest_once() -> dict | None:
    """수동 1회 수집 트리거(admin 용). busy 면 None 반환."""
    return run_ingest_guarded()
