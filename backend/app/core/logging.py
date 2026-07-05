"""로깅 설정.

`settings.LOG_LEVEL` 을 반영해 루트 로거를 구성한다.
애플리케이션 진입점(스케줄러·API 등)에서 `setup_logging()` 을 한 번 호출한다.
"""

from __future__ import annotations

import logging

from app.core.config import settings

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    """LOG_LEVEL 을 반영해 루트 로거를 1회 설정한다(멱등)."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """모듈용 로거를 반환한다. 최초 호출 시 로깅을 설정한다."""
    setup_logging()
    return logging.getLogger(name)
