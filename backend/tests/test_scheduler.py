"""스케줄러 중복 실행 방지 테스트 (네트워크 없음).

run_ingest 를 가짜로 대체해 락(busy) 동작만 검증한다.
"""

from __future__ import annotations

import app.core.scheduler as sched


def test_trigger_runs_when_free(monkeypatch) -> None:
    monkeypatch.setattr(sched, "run_ingest", lambda: {"ingested": 3})
    assert sched.trigger_ingest_once() == {"ingested": 3}


def test_trigger_returns_none_when_busy(monkeypatch) -> None:
    monkeypatch.setattr(sched, "run_ingest", lambda: {"ingested": 1})
    # 이미 수집이 진행 중인 상황을 모사: 락을 미리 점유
    assert sched._ingest_lock.acquire(blocking=False)
    try:
        assert sched.trigger_ingest_once() is None  # busy → 건너뜀
    finally:
        sched._ingest_lock.release()


def test_lock_released_after_run(monkeypatch) -> None:
    monkeypatch.setattr(sched, "run_ingest", lambda: {"ingested": 0})
    sched.trigger_ingest_once()
    # 실행 후 락이 반드시 해제되어 다음 실행이 가능해야 함
    assert sched._ingest_lock.acquire(blocking=False)
    sched._ingest_lock.release()


def test_exception_does_not_leak_lock(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(sched, "run_ingest", _boom)
    assert sched.trigger_ingest_once() is None  # 예외는 None 으로 흡수
    # 예외가 나도 락은 해제되어야 함
    assert sched._ingest_lock.acquire(blocking=False)
    sched._ingest_lock.release()
