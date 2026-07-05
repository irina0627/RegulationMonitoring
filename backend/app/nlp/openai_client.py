"""OpenAI 기반 LLMClient 구현 (설계서 12장).

외부 LLM 호출은 이 파일에만 존재한다. API 키는 Settings(OPENAI_API_KEY)에서만 읽는다.
모델명·파라미터는 상수로 두어 교체 가능하게 한다(모델·요금은 platform.openai.com 참조).

각 작업 함수는:
  프롬프트(prompts/) → OpenAI 호출 → JSON 파싱·스키마 검증(validation)
형식 불일치 시 1회 재시도하고, 그래도 실패하면 안전 폴백을 반환한다(설계서 12.3).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, TypeVar

from openai import OpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.nlp import prompts
from app.nlp.llm_client import Entity, Impact, Summary
from app.nlp.validation import (
    SchemaError,
    parse_entities,
    parse_impact,
    parse_lifecycle,
    parse_summary,
)

log = get_logger(__name__)

# --- 호출 파라미터 (상수화 — 교체 가능) ------------------------------------- #
DEFAULT_TEMPERATURE = 0.0  # 사실 기반, 재현성 우선
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = 30.0
DEFAULT_NET_RETRIES = 2  # 네트워크/디코딩 오류 재시도
SCHEMA_RETRIES = 1  # 스키마 불일치 시 재시도 횟수(설계서 12.3)
DEFAULT_BACKOFF = 0.5

# 본문 과다 토큰 방지용 컷(대략). 필요 시 청크 요약으로 확장.
MAX_INPUT_CHARS = 12000

T = TypeVar("T")


class OpenAIClient:
    """OpenAI Chat Completions 로 LLMClient 인터페이스를 구현한다."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_NET_RETRIES,
    ) -> None:
        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY 가 설정되지 않았습니다(.env). LLM 호출 불가."
            )
        self._client = OpenAI(api_key=key, timeout=timeout, max_retries=0)
        self._model = model or settings.LLM_MODEL
        self._retries = retries

    # --- 네트워크 호출 (JSON 강제) --------------------------------------- #
    def _chat_json(self, system: str, user: str) -> dict[str, Any]:
        """system/user 프롬프트로 JSON 응답을 받아 파싱한다. 타임아웃·재시도·로깅."""
        attempts = self._retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    temperature=DEFAULT_TEMPERATURE,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = resp.choices[0].message.content or "{}"
                return json.loads(content)
            except Exception as exc:  # noqa: BLE001 - 재시도/로깅 목적
                last_exc = exc
                log.warning(
                    "LLM 호출 실패 (attempt %d/%d): %s", attempt, attempts, exc
                )
                if attempt < attempts:
                    time.sleep(DEFAULT_BACKOFF * attempt)
        raise RuntimeError("LLM 호출 최종 실패") from last_exc

    # --- 검증 포함 호출 (스키마 불일치 1회 재시도 → 폴백) ------------------ #
    def _call_validated(
        self,
        system: str,
        text: str,
        parser: Callable[[Any], T],
        fallback: Callable[[], T],
        *,
        label: str,
    ) -> T:
        user = text[:MAX_INPUT_CHARS]
        attempts = SCHEMA_RETRIES + 1
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                data = self._chat_json(system, user)
                return parser(data)  # SchemaError 시 재시도
            except SchemaError as exc:
                last_err = exc
                log.warning("[%s] 스키마 불일치 (attempt %d/%d): %s",
                            label, attempt, attempts, exc)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("[%s] 호출 실패 (attempt %d/%d): %s",
                            label, attempt, attempts, exc)
        log.error("[%s] 검증 실패 — 안전 폴백 반환: %s", label, last_err)
        return fallback()

    # --- LLMClient 인터페이스 -------------------------------------------- #
    def summarize(self, text: str) -> Summary:
        return self._call_validated(
            prompts.SUMMARIZE_SYSTEM, text, parse_summary,
            lambda: Summary(summary="", why_it_matters=""), label="summarize",
        )

    def extract_entities(self, text: str) -> list[Entity]:
        return self._call_validated(
            prompts.ENTITIES_SYSTEM, text, parse_entities,
            lambda: [], label="entities",
        )

    def classify_lifecycle(self, text: str) -> str:
        return self._call_validated(
            prompts.LIFECYCLE_SYSTEM, text, parse_lifecycle,
            lambda: "", label="lifecycle",
        )

    def assess_impact(self, text: str) -> Impact:
        return self._call_validated(
            prompts.IMPACT_SYSTEM, text, parse_impact,
            lambda: Impact(), label="impact",
        )
