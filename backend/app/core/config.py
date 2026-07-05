"""애플리케이션 설정 (설정 외부화).

모든 환경변수는 이 `Settings` 를 통해서만 접근한다.
코드 어디에서도 URL·키·SMTP 정보를 하드코딩하지 않는다. (CLAUDE.md 아키텍처 원칙 2)

사용 예:
    from app.core.config import settings
    print(settings.FSC_RSS_PRESS)
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 리포지토리 루트 (.env 위치). 이 파일: backend/app/core/config.py → parents[3] = 루트
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """환경변수(.env)를 읽어들이는 설정 객체.

    지금 당장 쓰지 않는 키(LLM·SMTP·공공 API)는 비어 있어도 되도록 선택값(Optional)으로 둔다.
    """

    # --- DB ---
    DATABASE_URL: str | None = None

    # --- 수집 (M1) ---
    FSC_RSS_PRESS: str = "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111"
    FSC_BOARD_URL: str = "https://www.fsc.go.kr/no010101"
    POLL_INTERVAL_MIN: int = 10

    # --- 로깅 ---
    LOG_LEVEL: str = "INFO"

    # --- LLM (M2) ---
    OPENAI_API_KEY: str | None = None
    LLM_PROVIDER: str = "openai"  # 사내 이전 시 onprem|rule 로 교체
    LLM_MODEL: str = "gpt-4o-mini"  # 기본 모델. 필요 시 다른 OpenAI 모델로 교체
    # 임베딩(클러스터링용). local=오프라인 해싱, openai=API. 사내망 시 local 우선
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # --- 이메일 (M4) ---
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True  # 465 포트면 SSL, 그 외엔 STARTTLS 사용
    EMAIL_FROM: str | None = None
    EMAIL_PROVIDER: str = "smtp"  # 사내 이전 시 internal_relay 로 교체
    DIGEST_SEND_HOUR: int = 8  # 매일 발송 시각(24h)
    SEND_EMPTY_DIGEST: bool = False  # 신규 없을 때 발송 여부

    # --- 공공 API (M5) ---
    DATA_GO_KR_API_KEY: str | None = None
    LAW_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # .env 의 미정의 키는 무시
    )


# 전역 싱글턴. 모든 모듈은 이 인스턴스를 import 해서 사용한다.
settings = Settings()
