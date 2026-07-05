"""금융위 보도자료 RSS 수집기 (M1).

역할: RSS 를 폴링해 신규 보도자료 발생을 감지한다. (본문은 게시판/첨부에서 별도 수집)

설계 원칙(CLAUDE.md):
- 외부 네트워크 호출은 이 파일의 `fetch_feed()` 안에서만 일어난다.
- 파싱(`parse_feed`)·신규 판별(`select_new`)은 순수 함수 → 네트워크·DB 없이 테스트 가능.
- 수집 결과는 직렬화 가능한 표준 레코드(dict)로 반환한다(사내망 DMZ 경계 통과 단위).

표준 레코드 형태:
    {"rss_guid": str | None, "title": str | None,
     "published_at": datetime | None, "source_url": str | None}
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.press_release import PressRelease

log = get_logger(__name__)

# 표준 레코드 타입 별칭
Record = dict[str, Any]


# --------------------------------------------------------------------------- #
# 외부 호출 (이 함수 안에서만 네트워크 접근)
# --------------------------------------------------------------------------- #
def fetch_feed(
    url: str | None = None,
    *,
    retries: int = 2,
    timeout: float = 10.0,
    backoff: float = 0.5,
) -> bytes:
    """RSS 원문을 가져온다. 타임아웃·간단 재시도·에러 로깅 포함.

    바이트를 그대로 반환해 feedparser 가 XML 선언의 인코딩(EUC-KR/UTF-8 등)을
    스스로 감지하게 한다.
    """
    url = url or settings.FSC_RSS_PRESS
    attempts = retries + 1
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 - 재시도/로깅 목적
            last_exc = exc
            log.warning(
                "RSS 호출 실패 (attempt %d/%d) url=%s: %s", attempt, attempts, url, exc
            )
            if attempt < attempts:
                time.sleep(backoff * attempt)

    raise RuntimeError(f"RSS 호출 실패: {url}") from last_exc


# --------------------------------------------------------------------------- #
# 파싱 (순수 함수 — 네트워크 없음)
# --------------------------------------------------------------------------- #
def _parse_published(entry: Any) -> datetime | None:
    """feedparser 의 published_parsed(struct_time, UTC) → tz-aware datetime."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return datetime(*t[:6], tzinfo=timezone.utc)


def _guid_of(entry: Any) -> str | None:
    """항목의 guid. 없으면 링크의 sha256 해시를 guid 로 사용한다."""
    guid = entry.get("id") or entry.get("guid")
    if guid:
        return str(guid)
    link = entry.get("link")
    if link:
        return hashlib.sha256(link.encode("utf-8")).hexdigest()
    return None


def to_record(entry: Any) -> Record:
    """feedparser 항목 → 표준 레코드(dict)."""
    link = entry.get("link")
    return {
        "rss_guid": _guid_of(entry),
        "title": entry.get("title"),
        "published_at": _parse_published(entry),
        "source_url": link or None,
    }


def parse_feed(data: str | bytes) -> list[Record]:
    """RSS XML(문자열/바이트) → 표준 레코드 리스트. (네트워크 없음)"""
    feed = feedparser.parse(data)
    if getattr(feed, "bozo", 0) and getattr(feed, "entries", None) == []:
        log.warning("RSS 파싱 경고(bozo): %s", getattr(feed, "bozo_exception", ""))
    return [to_record(e) for e in feed.entries]


# --------------------------------------------------------------------------- #
# 수집 = 외부 호출 + 파싱
# --------------------------------------------------------------------------- #
def fetch_records(url: str | None = None) -> list[Record]:
    """RSS 를 호출해 표준 레코드 리스트를 반환한다."""
    return parse_feed(fetch_feed(url))


# --------------------------------------------------------------------------- #
# 신규 판별
# --------------------------------------------------------------------------- #
def select_new(records: list[Record], existing_guids: set[str]) -> list[Record]:
    """이미 저장된 guid 집합과 대조해 신규 레코드만 반환한다. (순수 함수)

    guid 가 없는 레코드는 중복 판별이 불가능하므로 신규로 취급한다.
    """
    result: list[Record] = []
    for r in records:
        guid = r.get("rss_guid")
        if guid is None or guid not in existing_guids:
            result.append(r)
    return result


def filter_new(records: list[Record], session: Session) -> list[Record]:
    """DB(press_release.rss_guid)와 대조해 신규 레코드만 반환한다.

    외부 호출은 없고 DB 조회만 한다. 실제 신규 판별의 진입점.
    """
    guids = [r["rss_guid"] for r in records if r.get("rss_guid")]
    if not guids:
        return list(records)

    rows = session.execute(
        select(PressRelease.rss_guid).where(PressRelease.rss_guid.in_(guids))
    ).scalars()
    existing = {g for g in rows if g is not None}
    new_records = select_new(records, existing)
    log.info("RSS 신규 판별: 전체 %d건 중 신규 %d건", len(records), len(new_records))
    return new_records
