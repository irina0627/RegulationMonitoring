"""영향 추정 프롬프트: 영향 업권·상품 + 근거. 투자권유 아님."""

from __future__ import annotations

from app.nlp.prompts._base import BASE_SYSTEM, ONTOLOGY

IMPACT_SYSTEM = (
    BASE_SYSTEM
    + ONTOLOGY
    + """

[작업] 이 규제가 영향을 주는 업권·상품을 추정한다.
※ 전제: 이 추정은 내부 참고용이며 투자권유가 아니다.
- sectors: 영향받는 업권(온톨로지 용어).
- products: 영향받는 상품.
- rationale: 그렇게 판단한 근거 문장(본문 사실 기반).
- 불확실하거나 근거가 약하면 해당 항목을 비워 둔다.

[출력 JSON 스키마]
{"sectors": ["<업권>"], "products": ["<상품>"], "rationale": "<문자열>"}
"""
)
