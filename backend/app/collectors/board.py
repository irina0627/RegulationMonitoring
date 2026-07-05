"""금융위 보도자료 상세 페이지 수집기 (M1).

RSS 로 감지한 항목의 상세 페이지에서 담당부서(dept)와 첨부파일 목록을 추출한다.
본문은 첨부(hwp/hwpx/pdf)에 있으므로, 여기서는 첨부 URL 까지만 확보한다(파싱은 7장 parsers/).

설계 원칙(CLAUDE.md):
- 외부 네트워크 호출은 이 파일의 `fetch_detail()` 안에서만 일어난다.
- `parse_detail()` 은 순수 함수 → 저장된 HTML 픽스처로 네트워크 없이 테스트 가능.
- 사이트 구조 변경에 대비해 선택자는 아래 상수(SEL_*)에 모아둔다. 추출 실패 시 빈 값 + 경고.

--------------------------------------------------------------------------
실제 상세 페이지 구조 (2026-07 확인, 예: https://www.fsc.go.kr/no010101/87252)
--------------------------------------------------------------------------
담당부서:
  div.board-view-wrap > div.header > div.info
    └ <span><strong>담당부서</strong> 금융정책과</span>
    └ <span><strong>담당자</strong> 김재민 사무관</span>

첨부파일 (각 첨부가 하나의 div.file-list):
  div.file > div.body ... div.file-list-wrap > div.file-list
    ├ <a href="/comm/getFile?srvcId=BBSTY1&upperNo=87252&fileTy=ATTACH&fileNo=1"
    │     title="....hwp"><span class="name">260703....hwp</span></a>   ← 파일명 링크(직접 자식 a)
    ├ <span class="name">(304 KB)</span>
    └ <span class="ico download"><a ...>파일다운로드</a></span>          ← 중첩 링크(제외 대상)
  href 는 상대경로 → base_url 로 절대경로화.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger

log = get_logger(__name__)

Record = dict[str, Any]

# --- 선택자 (사이트 구조 변경 시 여기만 수정) --------------------------------- #
SEL_INFO = "div.board-view-wrap div.header div.info"  # 담당부서/담당자 영역
DEPT_LABEL = "담당부서"
SEL_ATTACH_ANCHOR = "div.file-list-wrap div.file-list > a"  # 파일명 링크(직접 자식 a)
SEL_ATTACH_NAME = "span.name"  # 파일명 텍스트
KNOWN_FILE_TYPES = {"hwp", "hwpx", "pdf"}


# --------------------------------------------------------------------------- #
# 외부 호출 (이 함수 안에서만 네트워크 접근)
# --------------------------------------------------------------------------- #
def fetch_detail(
    url: str,
    *,
    retries: int = 2,
    timeout: float = 15.0,
    backoff: float = 0.5,
) -> bytes:
    """상세 페이지 HTML(bytes)을 가져온다. 타임아웃·간단 재시도·에러 로깅 포함."""
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
                "상세 페이지 호출 실패 (attempt %d/%d) url=%s: %s",
                attempt, attempts, url, exc,
            )
            if attempt < attempts:
                time.sleep(backoff * attempt)

    raise RuntimeError(f"상세 페이지 호출 실패: {url}") from last_exc


# --------------------------------------------------------------------------- #
# 파싱 (순수 함수 — 네트워크 없음)
# --------------------------------------------------------------------------- #
def _file_type(filename: str) -> str | None:
    """파일명 확장자로 타입 판별(hwp/hwpx/pdf). 그 외는 확장자 그대로, 없으면 None."""
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].strip().lower()
    return ext or None


def _extract_dept(soup: BeautifulSoup) -> str | None:
    """담당부서 텍스트를 추출한다. 실패 시 None + 경고."""
    scope = soup.select_one(SEL_INFO) or soup
    strong = scope.find("strong", string=lambda s: bool(s) and DEPT_LABEL in s)
    if strong is None or strong.parent is None:
        log.warning("담당부서 추출 실패(선택자 불일치)")
        return None
    raw = strong.parent.get_text(" ", strip=True)  # "담당부서 금융정책과"
    dept = re.sub(rf"^\s*{re.escape(DEPT_LABEL)}\s*", "", raw).strip()
    return dept or None


def _extract_attachments(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """첨부파일 목록 [{filename, type, url}] 을 추출한다. 실패/없음 시 [] + 경고."""
    attachments: list[dict] = []
    for a in soup.select(SEL_ATTACH_ANCHOR):
        href = a.get("href")
        if not href:
            continue
        name_el = a.select_one(SEL_ATTACH_NAME)
        filename = (
            name_el.get_text(strip=True)
            if name_el
            else (a.get("title") or a.get_text(strip=True))
        )
        attachments.append(
            {
                "filename": filename or None,
                "type": _file_type(filename or ""),
                "url": urljoin(base_url, href),
            }
        )

    if not attachments:
        log.warning("첨부파일 추출 결과 없음 base_url=%s", base_url)
    return attachments


def parse_detail(html: str | bytes, base_url: str) -> dict:
    """상세 페이지 HTML → {dept, attachments}. (네트워크 없음)"""
    soup = BeautifulSoup(html, "lxml")
    return {
        "dept": _extract_dept(soup),
        "attachments": _extract_attachments(soup, base_url),
    }


# --------------------------------------------------------------------------- #
# 수집 = 외부 호출 + 파싱 + RSS 레코드 병합
# --------------------------------------------------------------------------- #
def collect_detail(record: Record) -> Record:
    """RSS 표준 레코드에 상세정보(dept, attachments)를 병합해 반환한다.

    입력: source_url 을 가진 RSS 레코드.
    추출/호출 실패해도 예외를 던지지 않고 dept=None, attachments=[] 로 병합한다.
    (graceful degradation — 파이프라인을 멈추지 않음)
    """
    url = record.get("source_url")
    if not url:
        log.warning("source_url 없음 — 상세 수집 건너뜀 (guid=%s)", record.get("rss_guid"))
        return {**record, "dept": None, "attachments": []}

    try:
        html = fetch_detail(url)
    except Exception as exc:  # noqa: BLE001 - 실패해도 레코드는 유지
        log.error("상세 페이지 수집 실패 url=%s: %s", url, exc)
        return {**record, "dept": None, "attachments": []}

    return {**record, **parse_detail(html, url)}
