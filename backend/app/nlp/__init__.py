"""NLP 어댑터 패키지.

get_llm_client(): LLM_PROVIDER 설정에 따라 LLMClient 구현체를 반환하는 팩토리.
현재는 openai 만 지원. 추후 onprem/rule 구현을 여기에 추가한다(사내망 대비).
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.nlp.llm_client import LLMClient

log = get_logger(__name__)


def get_llm_client(provider: str | None = None) -> LLMClient:
    """LLM_PROVIDER 에 맞는 LLMClient 구현체를 반환한다.

    provider 를 직접 넘기면 그것을 우선한다(기본은 settings.LLM_PROVIDER).
    """
    name = (provider or settings.LLM_PROVIDER or "openai").strip().lower()

    if name == "openai":
        # 지연 import: openai 패키지 미설치 환경(rule/onprem)에서 import 비용 회피
        from app.nlp.openai_client import OpenAIClient

        return OpenAIClient()

    # 추후: "onprem" -> OnPremClient(), "rule" -> RuleBasedClient()
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {name!r}")


__all__ = ["get_llm_client", "LLMClient"]
