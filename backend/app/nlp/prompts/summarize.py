"""요약 프롬프트: 한 줄 요약 + 왜 중요한가."""

from __future__ import annotations

from app.nlp.prompts._base import BASE_SYSTEM

SUMMARIZE_SYSTEM = (
    BASE_SYSTEM
    + """

[작업] 보도자료 본문을 요약한다.
- summary: 핵심을 1~2문장으로 요약. 사실 기반.
- why_it_matters: 이 사안이 왜 중요한지를 대응 필요성·영향 관점에서 직접 서술한다.
  * "증권사 임직원", "임직원은", "독자" 같은 독자 지칭 표현으로 시작하거나 그런 표현을 쓰지 말 것.
  * 사안 자체의 의미·영향·대응 포인트를 서술한다. 투자권유가 아니다.
  * 예) (X) "증권사 임직원은 ~를 유의해야 한다"  (O) "~로 인해 ~ 대응이 필요하다"

[출력 JSON 스키마]
{"summary": "<문자열>", "why_it_matters": "<문자열>"}
"""
)
