"""이메일 발송 어댑터 (설계서 10.4).

외부 메일 발송은 이 파일 안에서만 일어난다. SMTP 설정은 Settings 에서만 읽는다.
사내망 이전 시 EmailSender 구현만 사내 메일 릴레이(InternalRelaySender)로 교체한다.
"""

from __future__ import annotations

import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.5


@dataclass
class SendResult:
    """발송 결과. 실패해도 예외 대신 이 결과를 반환한다."""

    ok: bool
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    error: str | None = None


@runtime_checkable
class EmailSender(Protocol):
    """발송 인터페이스. 코어(digest)는 이 인터페이스에만 의존한다."""

    def send(self, to: list[str], subject: str, html: str) -> SendResult:
        ...


class SmtpSender:
    """SMTP 발송 구현. 설정은 Settings 에서 읽고, 재시도·에러 로깅·실패 반환."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self._host = settings.SMTP_HOST
        self._port = settings.SMTP_PORT
        self._user = settings.SMTP_USER
        self._password = settings.SMTP_PASSWORD
        self._starttls = settings.SMTP_STARTTLS
        self._from = settings.EMAIL_FROM or settings.SMTP_USER
        self._timeout = timeout
        self._retries = retries

    def _build_message(self, to: list[str], subject: str, html: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content("이 메일은 HTML 형식입니다. HTML 을 지원하는 클라이언트에서 확인하세요.")
        msg.add_alternative(html, subtype="html")
        return msg

    def _connect(self) -> smtplib.SMTP:
        """포트에 따라 SMTP_SSL(465) 또는 SMTP(+STARTTLS)로 연결한다."""
        if self._port == 465:
            return smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout)
        server = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
        if self._starttls:
            server.starttls()
        return server

    def send(self, to: list[str], subject: str, html: str) -> SendResult:
        if not self._host:
            msg = "SMTP_HOST 미설정 — 발송 불가(.env 확인)"
            log.error(msg)
            return SendResult(ok=False, rejected=list(to), error=msg)
        if not self._from:
            msg = "EMAIL_FROM/SMTP_USER 미설정 — 발신자 없음"
            log.error(msg)
            return SendResult(ok=False, rejected=list(to), error=msg)
        if not to:
            return SendResult(ok=True)  # 수신자 없으면 성공(발송 생략)

        message = self._build_message(to, subject, html)
        attempts = self._retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                with self._connect() as server:
                    if self._user and self._password:
                        server.login(self._user, self._password)
                    refused = server.send_message(message)  # {addr: (code, msg)}
                rejected = list(refused.keys())
                accepted = [a for a in to if a not in rejected]
                if rejected:
                    log.warning("일부 수신자 거부: %s", rejected)
                log.info("메일 발송: subject=%r 수신 %d명(성공 %d)", subject, len(to), len(accepted))
                return SendResult(ok=not rejected, accepted=accepted, rejected=rejected)
            except Exception as exc:  # noqa: BLE001 - 재시도/실패 반환
                last_exc = exc
                log.warning(
                    "SMTP 발송 실패 (attempt %d/%d): %s", attempt, attempts, exc
                )
                if attempt < attempts:
                    time.sleep(DEFAULT_BACKOFF * attempt)

        return SendResult(ok=False, rejected=list(to), error=str(last_exc))


def get_email_sender(provider: str | None = None) -> EmailSender:
    """EMAIL_PROVIDER 에 맞는 EmailSender 구현체를 반환한다(기본 smtp)."""
    name = (provider or settings.EMAIL_PROVIDER or "smtp").strip().lower()
    if name == "smtp":
        return SmtpSender()
    # 추후: "internal_relay" -> InternalRelaySender()
    raise ValueError(f"지원하지 않는 EMAIL_PROVIDER: {name!r}")
