"""DB 연결 확인 스크립트.

실행:
    cd backend && PYTHONPATH=. python scripts/check_db.py

DATABASE_URL(.env) 로 접속해 SELECT 1 과 서버 버전을 출력한다.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine


def main() -> int:
    print(f"DATABASE_URL: {settings.DATABASE_URL}")
    try:
        with engine.connect() as conn:
            one = conn.execute(text("SELECT 1")).scalar_one()
            version = conn.execute(text("SHOW server_version")).scalar_one()
        print(f"SELECT 1 → {one}")
        print(f"PostgreSQL server_version → {version}")
        print("DB 연결 성공 ✓")
        return 0
    except Exception as exc:  # noqa: BLE001 - 진단용 스크립트
        print(f"DB 연결 실패 ✗: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
