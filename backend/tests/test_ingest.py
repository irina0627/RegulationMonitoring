"""적재 파이프라인 e2e 테스트 (네트워크 없음, 실제 PostgreSQL).

mock 수집기/파서를 주입해 RSS→상세→다운로드→파싱→upsert 전 과정을 돌리고,
멱등성(2회 실행해도 행 증가 없음)과 본문 적재를 검증한다.

DB 는 docker-compose 의 postgres 를 사용한다. 테스트 guid 접두사로 격리·정리한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.collectors.ingest import run_ingest
from app.collectors.rss import filter_new  # 실제 DB 대조 dedup 사용
from app.core.db import SessionLocal
from app.models.press_release import PressRelease

GUID_PREFIX = "test-ingest-"
GUID_A = f"{GUID_PREFIX}aaaa"
GUID_B = f"{GUID_PREFIX}bbbb"


# --- mock 외부 의존 -------------------------------------------------------- #
def _mock_rss_fetch() -> list[dict]:
    return [
        {
            "rss_guid": GUID_A,
            "title": "PF 상황 점검회의",
            "published_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
            "source_url": "https://example.test/a",
        },
        {
            "rss_guid": GUID_B,
            "title": "청년미래적금 안내",
            "published_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
            "source_url": "https://example.test/b",
        },
    ]


def _mock_collect_detail(record: dict) -> dict:
    return {
        **record,
        "dept": "금융정책과",
        "attachments": [
            {"filename": "doc.pdf", "type": "pdf", "url": "https://example.test/doc.pdf"}
        ],
    }


def _mock_download(attachments, dest_dir=None, **kw):
    # 다운로드된 것처럼 local_path·parse_status 부여 (실제 파일 접근 없음)
    return [
        {**a, "local_path": f"/tmp/{a['filename']}", "parse_status": "downloaded"}
        for a in attachments
    ]


def _mock_parse(downloaded) -> dict:
    return {
        "body_text": "보도자료 본문 텍스트입니다.",
        "parse_status": "parsed",
        "source_file": downloaded[0]["local_path"] if downloaded else None,
    }


def _run() -> dict:
    return run_ingest(
        session_factory=SessionLocal,
        rss_fetch=_mock_rss_fetch,
        filter_new=filter_new,  # 실제 dedup
        collect_detail=_mock_collect_detail,
        download_attachments=_mock_download,
        parse_attachments=_mock_parse,
    )


@pytest.fixture(autouse=True)
def _cleanup():
    """테스트 전후로 test-ingest-* 행 제거."""
    def _purge():
        with SessionLocal() as s:
            s.execute(
                delete(PressRelease).where(PressRelease.rss_guid.like(f"{GUID_PREFIX}%"))
            )
            s.commit()

    _purge()
    yield
    _purge()


def _count() -> int:
    with SessionLocal() as s:
        rows = s.execute(
            select(PressRelease).where(PressRelease.rss_guid.like(f"{GUID_PREFIX}%"))
        ).scalars().all()
        return len(rows)


def test_ingest_inserts_and_fills_body() -> None:
    stats = _run()
    assert stats["new"] == 2
    assert stats["parsed_ok"] == 2
    assert stats["ingested"] == 2
    assert _count() == 2

    # 본문·부서·첨부가 채워졌는지 확인
    with SessionLocal() as s:
        row = s.execute(
            select(PressRelease).where(PressRelease.rss_guid == GUID_A)
        ).scalar_one()
        assert row.body_text == "보도자료 본문 텍스트입니다."
        assert row.dept == "금융정책과"
        assert row.parse_status == "parsed"
        assert row.attachments[0]["url"] == "https://example.test/doc.pdf"
        assert "local_path" not in row.attachments[0]  # 임시경로는 저장 안 함


def test_ingest_is_idempotent() -> None:
    first = _run()
    assert first["new"] == 2
    assert _count() == 2

    # 2회차: 이미 존재 → filter_new 가 걸러 신규 0건, 행 수 불변
    second = _run()
    assert second["new"] == 0
    assert second["ingested"] == 0
    assert _count() == 2  # 중복 행 생기지 않음


def test_upsert_updates_existing_row_without_duplicate() -> None:
    from app.collectors.ingest import upsert_press_release

    with SessionLocal() as s:
        upsert_press_release(s, {"rss_guid": GUID_A, "title": "v1", "body_text": "old"})
        s.commit()
    with SessionLocal() as s:
        # 같은 guid 로 다시 upsert → update
        upsert_press_release(s, {"rss_guid": GUID_A, "title": "v2", "body_text": "new"})
        s.commit()

    with SessionLocal() as s:
        rows = s.execute(
            select(PressRelease).where(PressRelease.rss_guid == GUID_A)
        ).scalars().all()
        assert len(rows) == 1  # 중복 insert 아님
        assert rows[0].title == "v2"  # 갱신됨
        assert rows[0].body_text == "new"
