"""첨부 다운로더 단위 테스트.

로컬 더미 HTTP 파일 서버로 다운로드 성공/실패/크기상한 동작을 검증한다.
(외부 네트워크 없음)
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from app.collectors.attachment import download_attachments, download_one


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 테스트 로그 소음 제거
        pass


@pytest.fixture()
def file_server(tmp_path: Path):
    """tmp_path 를 서빙하는 로컬 HTTP 서버. base_url 반환."""
    served = tmp_path / "served"
    served.mkdir()
    handler = lambda *a, **k: _Handler(*a, directory=str(served), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield served, f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_download_success(file_server, tmp_path: Path) -> None:
    served, base = file_server
    (served / "report.pdf").write_bytes(b"%PDF-1.4 dummy content")

    atts = [{"filename": "report.pdf", "type": "pdf", "url": f"{base}/report.pdf"}]
    out = download_attachments(atts, dest_dir=tmp_path / "dl")

    assert len(out) == 1
    r = out[0]
    assert r["parse_status"] == "downloaded"
    assert r["local_path"] is not None
    saved = Path(r["local_path"])
    assert saved.exists()
    assert saved.read_bytes() == b"%PDF-1.4 dummy content"


def test_download_failure_marks_failed_and_continues(file_server, tmp_path: Path) -> None:
    served, base = file_server
    (served / "ok.hwp").write_bytes(b"hwp-bytes")

    atts = [
        {"filename": "missing.pdf", "type": "pdf", "url": f"{base}/nope.pdf"},  # 404
        {"filename": "ok.hwp", "type": "hwp", "url": f"{base}/ok.hwp"},  # 성공
    ]
    # 재시도 0회로 테스트 빠르게
    out = [
        download_one(a, tmp_path / "dl2", index=i, retries=0)
        for i, a in enumerate(atts)
    ]

    assert out[0]["parse_status"] == "failed"
    assert out[0]["local_path"] is None
    # 실패해도 다음 첨부는 정상 처리
    assert out[1]["parse_status"] == "downloaded"
    assert Path(out[1]["local_path"]).exists()


def test_size_cap_rejects_large_file(file_server, tmp_path: Path) -> None:
    served, base = file_server
    (served / "big.pdf").write_bytes(b"x" * 5000)

    atts = [{"filename": "big.pdf", "type": "pdf", "url": f"{base}/big.pdf"}]
    # 상한을 1000바이트로 낮춰 초과 유도
    out = download_attachments(atts, dest_dir=tmp_path / "dl3", max_bytes=1000, retries=0)

    assert out[0]["parse_status"] == "failed"
    assert out[0]["local_path"] is None
    # 초과 파일은 저장되지 않음
    assert not (tmp_path / "dl3" / "big.pdf").exists()


def test_missing_url_marks_failed(tmp_path: Path) -> None:
    out = download_attachments(
        [{"filename": "x.pdf", "type": "pdf", "url": None}], dest_dir=tmp_path / "dl4"
    )
    assert out[0]["parse_status"] == "failed"
    assert out[0]["local_path"] is None


def test_unsafe_filename_is_sanitized(file_server, tmp_path: Path) -> None:
    served, base = file_server
    (served / "evil.pdf").write_bytes(b"data")
    # 경로 조작 시도 파일명 → basename 만 사용
    atts = [{"filename": "../../etc/passwd", "type": None, "url": f"{base}/evil.pdf"}]
    out = download_attachments(atts, dest_dir=tmp_path / "dl5")

    saved = Path(out[0]["local_path"])
    assert saved.parent == (tmp_path / "dl5")  # 상위 디렉토리로 탈출하지 않음
    assert saved.name == "passwd"
