"""이메일 발송 어댑터 테스트 (SMTP mock, 실제 발송 없음)."""

from __future__ import annotations

import pytest

import app.email.sender as sender_mod
from app.email.sender import EmailSender, SendResult, SmtpSender, get_email_sender


class FakeSMTP:
    """smtplib.SMTP 대체. 클래스 변수로 동작 제어."""

    refused: dict = {}
    raise_exc: Exception | None = None
    login_calls: list = []
    sent: list = []

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.raise_exc:
            raise FakeSMTP.raise_exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        FakeSMTP.login_calls.append((user, password))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)
        return dict(FakeSMTP.refused)


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.refused = {}
    FakeSMTP.raise_exc = None
    FakeSMTP.login_calls = []
    FakeSMTP.sent = []
    yield


@pytest.fixture()
def smtp_configured(monkeypatch):
    # SMTP 설정 주입 + SMTP 클래스 mock
    monkeypatch.setattr(sender_mod.settings, "SMTP_HOST", "smtp.test", raising=False)
    monkeypatch.setattr(sender_mod.settings, "SMTP_PORT", 587, raising=False)
    monkeypatch.setattr(sender_mod.settings, "SMTP_USER", "u@test", raising=False)
    monkeypatch.setattr(sender_mod.settings, "SMTP_PASSWORD", "pw", raising=False)
    monkeypatch.setattr(sender_mod.settings, "EMAIL_FROM", "from@test", raising=False)
    monkeypatch.setattr(sender_mod.smtplib, "SMTP", FakeSMTP)


# --- 팩토리 --------------------------------------------------------------- #
def test_factory_returns_smtp_sender() -> None:
    s = get_email_sender("smtp")
    assert isinstance(s, SmtpSender)
    assert isinstance(s, EmailSender)  # 구조적 인터페이스 만족


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        get_email_sender("carrier_pigeon")


# --- 발송 성공 ------------------------------------------------------------ #
def test_send_success(smtp_configured) -> None:
    s = SmtpSender()
    res = s.send(["a@x.com", "b@x.com"], "제목", "<p>본문</p>")
    assert isinstance(res, SendResult)
    assert res.ok is True
    assert set(res.accepted) == {"a@x.com", "b@x.com"}
    assert res.rejected == []
    assert FakeSMTP.login_calls == [("u@test", "pw")]  # 인증 호출됨
    assert len(FakeSMTP.sent) == 1


def test_send_partial_rejection(smtp_configured) -> None:
    FakeSMTP.refused = {"bad@x.com": (550, b"No such user")}
    s = SmtpSender()
    res = s.send(["ok@x.com", "bad@x.com"], "제목", "<p>hi</p>")
    assert res.ok is False  # 일부 거부 → ok=False
    assert res.accepted == ["ok@x.com"]
    assert res.rejected == ["bad@x.com"]


# --- 실패 처리(예외를 SendResult 로 흡수 + 재시도) ------------------------ #
def test_send_failure_returns_result_not_raise(smtp_configured) -> None:
    FakeSMTP.raise_exc = ConnectionError("연결 거부")
    s = SmtpSender(retries=1)
    res = s.send(["a@x.com"], "제목", "<p>hi</p>")
    assert res.ok is False
    assert res.rejected == ["a@x.com"]
    assert "연결 거부" in (res.error or "")


# --- 설정 누락 방어 ------------------------------------------------------- #
def test_send_without_host_returns_failure(monkeypatch) -> None:
    monkeypatch.setattr(sender_mod.settings, "SMTP_HOST", None, raising=False)
    s = SmtpSender()
    res = s.send(["a@x.com"], "제목", "<p>hi</p>")
    assert res.ok is False
    assert "SMTP_HOST" in (res.error or "")


def test_send_empty_recipients_is_ok(smtp_configured) -> None:
    s = SmtpSender()
    res = s.send([], "제목", "<p>hi</p>")
    assert res.ok is True
    assert FakeSMTP.sent == []  # 발송 생략
