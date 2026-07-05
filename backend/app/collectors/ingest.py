"""수집·파싱 파이프라인 → press_release 멱등 적재 (M1).

흐름: RSS 신규 감지 → 상세 수집(dept/첨부) → 첨부 다운로드 → 본문 파싱 → upsert.

멱등성(CLAUDE.md 원칙 3):
- rss_guid 를 유니크 키로 하는 upsert(ON CONFLICT DO UPDATE).
- 이미 있으면 본문/상태 등만 갱신, 신규면 insert. 같은 입력을 재실행해도 행이 늘지 않는다.

테스트 용이성:
- 외부 의존(RSS/상세/다운로드/파싱)은 인자로 주입 가능 → 네트워크 없이 e2e 검증.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.collectors import attachment as _attachment
from app.collectors import board as _board
from app.collectors import rss as _rss
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.models.press_release import PressRelease
from app.parsers import parse_attachments as _parse_attachments

log = get_logger(__name__)

Record = dict[str, Any]

# DB attachments(JSONB) 에 남길 필드 (임시 local_path 는 제외)
_ATT_FIELDS = ("filename", "type", "url", "parse_status")


def _attachments_for_db(downloaded: list[dict]) -> list[dict]:
    """다운로드 결과에서 DB 저장용 첨부 메타만 추린다(schema: [{filename,type,url,parse_status}])."""
    return [{k: a.get(k) for k in _ATT_FIELDS} for a in downloaded]


def upsert_press_release(session: Session, data: Record) -> None:
    """rss_guid 기준 upsert. 있으면 본문·상태 등 갱신, 없으면 insert.

    rss_guid 가 없으면 멱등 키가 없으므로 저장하지 않는다(경고).
    """
    guid = data.get("rss_guid")
    if not guid:
        log.warning("rss_guid 없음 — 적재 건너뜀 (title=%s)", data.get("title"))
        return

    stmt = pg_insert(PressRelease).values(
        rss_guid=guid,
        title=data.get("title"),
        published_at=data.get("published_at"),
        dept=data.get("dept"),
        source_url=data.get("source_url"),
        body_text=data.get("body_text"),
        attachments=data.get("attachments"),
        parse_status=data.get("parse_status", "pending"),
        fetched_at=func.now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["rss_guid"],  # press_release_rss_guid_key
        set_={
            "title": stmt.excluded.title,
            "published_at": stmt.excluded.published_at,
            "dept": stmt.excluded.dept,
            "source_url": stmt.excluded.source_url,
            "body_text": stmt.excluded.body_text,
            "attachments": stmt.excluded.attachments,
            "parse_status": stmt.excluded.parse_status,
            "fetched_at": func.now(),
        },
    )
    session.execute(stmt)


def run_ingest(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    rss_fetch: Callable[[], list[Record]] = _rss.fetch_records,
    filter_new: Callable[[list[Record], Session], list[Record]] = _rss.filter_new,
    collect_detail: Callable[[Record], Record] = _board.collect_detail,
    download_attachments: Callable[..., list[dict]] = _attachment.download_attachments,
    parse_attachments: Callable[[list[dict]], dict] = _parse_attachments,
    dest_dir: str | Path | None = None,
) -> dict:
    """수집→파싱→적재 파이프라인을 1회 실행하고 통계를 반환한다.

    반환: {"rss_total","new","parsed_ok","parse_failed","ingested"}
    """
    records = rss_fetch()
    log.info("RSS 수집: 전체 %d건", len(records))

    stats = {
        "rss_total": len(records),
        "new": 0,
        "parsed_ok": 0,
        "parse_failed": 0,
        "ingested": 0,
    }

    with session_factory() as session:
        new_records = filter_new(records, session)
        stats["new"] = len(new_records)

        for record in new_records:
            # 1) 상세(dept, attachments 메타)
            detail = collect_detail(record)

            # 2) 첨부 다운로드 (local_path 추가)
            downloaded = download_attachments(detail.get("attachments", []), dest_dir)

            # 3) 본문 파싱 (PDF 우선, HWP 폴백, 실패해도 failed 반환)
            parsed = parse_attachments(downloaded)
            if parsed["parse_status"] == "parsed":
                stats["parsed_ok"] += 1
            else:
                stats["parse_failed"] += 1

            # 4) upsert
            upsert_press_release(
                session,
                {
                    "rss_guid": record.get("rss_guid"),
                    "title": record.get("title"),
                    "published_at": record.get("published_at"),
                    "source_url": record.get("source_url"),
                    "dept": detail.get("dept"),
                    "body_text": parsed["body_text"],
                    "attachments": _attachments_for_db(downloaded),
                    "parse_status": parsed["parse_status"],
                },
            )
            stats["ingested"] += 1

        session.commit()

    log.info(
        "적재 완료: 신규 %d건, 파싱성공 %d건, 실패 %d건 (RSS 전체 %d건)",
        stats["new"], stats["parsed_ok"], stats["parse_failed"], stats["rss_total"],
    )
    return stats
