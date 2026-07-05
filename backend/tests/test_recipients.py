"""수신자 그룹 시드 로딩 + CRUD 테스트 (실제 PostgreSQL)."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.email import recipients as rc
from app.models.recipient import Recipient
from app.models.recipient_group import RecipientGroup

# 임시 시드 YAML
SEED_YAML = """
groups:
  - name: 파생업권
    filters:
      sectors: [증권]
      products: [ELS, DLS]
      keywords: [파생]
    recipients:
      - { email: a@x.com, name: A }
      - { email: b@x.com, name: B }
  - name: 컴플라이언스
    filters:
      keywords: [제재, 검사]
    recipients:
      - { email: c@x.com, name: C }
"""


@pytest.fixture(autouse=True)
def _clean():
    def _purge():
        with SessionLocal() as s:
            s.execute(delete(Recipient))
            s.execute(delete(RecipientGroup))
            s.commit()
    _purge()
    yield
    _purge()


@pytest.fixture()
def seed_file(tmp_path):
    p = tmp_path / "recipients.yaml"
    p.write_text(SEED_YAML, encoding="utf-8")
    return p


def _counts():
    with SessionLocal() as s:
        g = s.execute(select(func.count()).select_from(RecipientGroup)).scalar_one()
        r = s.execute(select(func.count()).select_from(Recipient)).scalar_one()
        return g, r


# --- 시드 로딩 ------------------------------------------------------------ #
def test_seed_loads_groups_and_recipients(seed_file) -> None:
    with SessionLocal() as s:
        stats = rc.load_seed(s, seed_file)
    assert stats["groups"] == 2
    assert stats["recipients_upserted"] == 3
    assert _counts() == (2, 3)

    with SessionLocal() as s:
        grp = s.execute(
            select(RecipientGroup).where(RecipientGroup.name == "파생업권")
        ).scalar_one()
        assert grp.filters["products"] == ["ELS", "DLS"]


def test_seed_is_idempotent(seed_file) -> None:
    with SessionLocal() as s:
        rc.load_seed(s, seed_file)
    with SessionLocal() as s:
        rc.load_seed(s, seed_file)  # 2회차
    assert _counts() == (2, 3)  # 중복 증가 없음


def test_seed_syncs_removed_recipient(seed_file, tmp_path) -> None:
    with SessionLocal() as s:
        rc.load_seed(s, seed_file)
    # 파생업권에서 b@x.com 제거한 시드로 재적재
    p2 = tmp_path / "r2.yaml"
    p2.write_text(
        "groups:\n  - name: 파생업권\n    filters: {sectors: [증권]}\n"
        "    recipients:\n      - { email: a@x.com, name: A }\n",
        encoding="utf-8",
    )
    with SessionLocal() as s:
        stats = rc.load_seed(s, p2)
    assert stats["recipients_removed"] == 1  # b@x.com 제거
    with SessionLocal() as s:
        emails = set(
            s.execute(select(Recipient.email)).scalars()
        )
    assert "b@x.com" not in emails


# --- 그룹 CRUD ------------------------------------------------------------ #
def test_group_crud() -> None:
    with SessionLocal() as s:
        g = rc.create_group(s, "리테일", {"sectors": ["은행"]}, True)
        gid = g["id"]
        assert g["name"] == "리테일"
        assert g["recipient_count"] == 0

        groups = rc.list_groups(s)
        assert len(groups) == 1

        updated = rc.update_group(s, gid, name="리테일상품부", active=False)
        assert updated["name"] == "리테일상품부"
        assert updated["active"] is False

        rc.delete_group(s, gid)
        assert rc.list_groups(s) == []


def test_update_missing_group_raises() -> None:
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            rc.update_group(s, 999999, name="x")


# --- 수신자 CRUD ---------------------------------------------------------- #
def test_recipient_crud() -> None:
    with SessionLocal() as s:
        g = rc.create_group(s, "그룹A", {})
        gid = g["id"]

        r = rc.add_recipient(s, gid, "x@x.com", "X")
        assert r["email"] == "x@x.com"

        lst = rc.list_recipients(s, gid)
        assert len(lst) == 1

        rc.delete_recipient(s, r["id"])
        assert rc.list_recipients(s, gid) == []


def test_add_recipient_duplicate_raises() -> None:
    with SessionLocal() as s:
        g = rc.create_group(s, "그룹B", {})
        rc.add_recipient(s, g["id"], "dup@x.com")
        with pytest.raises(ValueError):
            rc.add_recipient(s, g["id"], "dup@x.com")  # (group, email) 중복


def test_add_recipient_missing_group_raises() -> None:
    with SessionLocal() as s:
        with pytest.raises(LookupError):
            rc.add_recipient(s, 999999, "x@x.com")


def test_delete_group_removes_recipients() -> None:
    with SessionLocal() as s:
        g = rc.create_group(s, "그룹C", {})
        rc.add_recipient(s, g["id"], "m@x.com")
        rc.delete_group(s, g["id"])
        # 수신자도 삭제됨
        remaining = s.execute(select(func.count()).select_from(Recipient)).scalar_one()
        assert remaining == 0
