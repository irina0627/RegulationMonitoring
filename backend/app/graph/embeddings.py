"""임베딩 어댑터 (설계서 6.4 클러스터링 보조).

임베딩 구현을 인터페이스 뒤로 분리한다. 사내망/오프라인에선 LocalEmbedder(외부 의존 없음),
외부에선 OpenAIEmbedder 로 교체 가능(EMBEDDING_PROVIDER 설정).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

Vector = list[float]


@runtime_checkable
class Embedder(Protocol):
    """텍스트 목록을 벡터 목록으로 변환."""

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        ...


def cosine(a: Vector, b: Vector) -> float:
    """코사인 유사도. 음수·0 나눗셈은 0 으로 클램프하여 [0,1] 반환(비음수 벡터 기준)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


class LocalEmbedder:
    """경량 로컬 임베더: 단어 + 문자 n-gram 해싱 트릭.

    외부 의존 없음·결정적(hashlib 기반). 오프라인/사내망 기본값이자 테스트용.
    """

    def __init__(self, dim: int = 512, ngram: int = 2) -> None:
        self.dim = dim
        self.ngram = ngram

    def _grams(self, text: str) -> list[str]:
        t = (text or "").strip()
        grams = [w for w in re.split(r"[\s,·]+", t) if w]  # 단어 토큰
        s = re.sub(r"\s+", "", t)  # 문자 n-gram
        grams += [s[i : i + self.ngram] for i in range(max(0, len(s) - self.ngram + 1))]
        return grams

    def _vec(self, text: str) -> Vector:
        v = [0.0] * self.dim
        for g in self._grams(text):
            idx = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm > 0 else v

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._vec(t) for t in texts]


class OpenAIEmbedder:
    """OpenAI 임베딩 API 구현. (외부 호출)"""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        from openai import OpenAI

        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise RuntimeError("OPENAI_API_KEY 미설정 — OpenAIEmbedder 사용 불가")
        self._client = OpenAI(api_key=key, timeout=timeout, max_retries=2)
        self._model = model or settings.EMBEDDING_MODEL

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        resp = self._client.embeddings.create(model=self._model, input=list(texts))
        return [d.embedding for d in resp.data]


def get_embedder(provider: str | None = None) -> Embedder:
    """EMBEDDING_PROVIDER 에 맞는 임베더를 반환한다(기본 local)."""
    name = (provider or settings.EMBEDDING_PROVIDER or "local").strip().lower()
    if name == "local":
        return LocalEmbedder()
    if name == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"지원하지 않는 EMBEDDING_PROVIDER: {name!r}")
