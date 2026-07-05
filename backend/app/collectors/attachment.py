"""첨부파일 다운로더 (M1).

board.py 가 확보한 첨부 메타[{filename, type, url}] 를 받아 실제 파일을 내려받고,
저장 경로(local_path)와 상태(parse_status)를 메타에 추가해 반환한다.

설계 원칙(CLAUDE.md):
- 외부 네트워크 호출은 이 파일 안에서만.
- graceful degradation: 다운로드 실패한 첨부는 parse_status='failed' 로 표시하고 넘어간다.
  (전체 파이프라인을 멈추지 않음)
- 안전장치: 파일 크기 상한(MAX_FILE_BYTES)으로 비정상적으로 큰 파일을 거른다(스트리밍 검사).
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

Attachment = dict[str, Any]

# 안전장치: 첨부 최대 크기 (기본 50MB). 보도자료 hwp/pdf 는 통상 수 MB.
MAX_FILE_BYTES = 50 * 1024 * 1024
_CHUNK = 64 * 1024

# 다운로드 저장 기본 위치 (임시 경로)
DEFAULT_DEST_DIR = Path(tempfile.gettempdir()) / "fsc_attachments"


class _TooLarge(Exception):
    """크기 상한 초과."""


def _safe_filename(filename: str | None, fallback: str) -> str:
    """경로 조작·구분자 제거한 안전한 파일명. 비면 fallback 사용."""
    name = (filename or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or fallback


# --------------------------------------------------------------------------- #
# 외부 호출 (이 함수 안에서만 네트워크 접근)
# --------------------------------------------------------------------------- #
def _stream_to_file(
    url: str, dest: Path, *, timeout: float, max_bytes: int
) -> int:
    """url 을 스트리밍으로 dest 에 저장. 크기 상한 초과 시 _TooLarge. 저장 바이트 수 반환."""
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()

        # 1차 방어: Content-Length 헤더로 조기 차단
        declared = resp.headers.get("content-length")
        if declared and int(declared) > max_bytes:
            raise _TooLarge(f"content-length {declared} > {max_bytes}")

        # 2차 방어: 실제 스트리밍 바이트 누적 검사
        total = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise _TooLarge(f"streamed {total} > {max_bytes}")
                f.write(chunk)
    return total


def download_one(
    att: Attachment,
    dest_dir: Path,
    *,
    index: int = 0,
    retries: int = 2,
    timeout: float = 30.0,
    backoff: float = 0.5,
    max_bytes: int = MAX_FILE_BYTES,
) -> Attachment:
    """첨부 1건을 내려받아 local_path·parse_status 를 추가한 새 메타를 반환한다.

    성공: parse_status='downloaded', local_path=<경로>
    실패: parse_status='failed', local_path=None  (예외를 던지지 않음)
    """
    result = {**att, "local_path": None, "parse_status": "failed"}
    url = att.get("url")
    if not url:
        log.warning("첨부 url 없음 — 건너뜀 (filename=%s)", att.get("filename"))
        return result

    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(att.get("filename"), fallback=f"attachment_{index}")
    dest = dest_dir / filename

    attempts = retries + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            size = _stream_to_file(url, dest, timeout=timeout, max_bytes=max_bytes)
            log.info("첨부 다운로드 성공 %s (%d bytes)", dest.name, size)
            result["local_path"] = str(dest)
            result["parse_status"] = "downloaded"
            return result
        except _TooLarge as exc:
            # 크기 초과는 재시도 무의미 → 즉시 실패 처리
            log.warning("첨부 크기 상한 초과 url=%s: %s", url, exc)
            dest.unlink(missing_ok=True)
            return result
        except Exception as exc:  # noqa: BLE001 - 재시도/실패 표시 목적
            last_exc = exc
            log.warning(
                "첨부 다운로드 실패 (attempt %d/%d) url=%s: %s",
                attempt, attempts, url, exc,
            )
            dest.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(backoff * attempt)

    log.error("첨부 다운로드 최종 실패 url=%s: %s", url, last_exc)
    return result


def download_attachments(
    attachments: list[Attachment],
    dest_dir: str | Path | None = None,
    *,
    max_bytes: int = MAX_FILE_BYTES,
    **kwargs: Any,
) -> list[Attachment]:
    """첨부 메타 리스트를 모두 내려받아 local_path·parse_status 가 추가된 리스트를 반환한다.

    개별 실패는 parse_status='failed' 로 표시하고 계속 진행한다(중단 금지).
    """
    dest = Path(dest_dir) if dest_dir else DEFAULT_DEST_DIR
    dest.mkdir(parents=True, exist_ok=True)

    results: list[Attachment] = []
    for i, att in enumerate(attachments):
        results.append(download_one(att, dest, index=i, max_bytes=max_bytes, **kwargs))

    ok = sum(1 for r in results if r["parse_status"] == "downloaded")
    log.info("첨부 다운로드 완료: 전체 %d건 중 성공 %d건", len(results), ok)
    return results
