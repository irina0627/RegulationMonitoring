"""엔터티 추출 프롬프트: 법령/상품/업권/부서/시행일 → 온톨로지 정규화."""

from __future__ import annotations

from app.nlp.prompts._base import BASE_SYSTEM, ONTOLOGY

ENTITIES_SYSTEM = (
    BASE_SYSTEM
    + ONTOLOGY
    + """

[작업] 본문에서 아래 엔터티를 추출하고 시드 온톨로지 용어로 정규화한다.
대상: 법령명, 금융상품, 업권, 소관부서, (법령이면) 시행일.
- type: regulation|product|sector|agency|dept 중 하나.
- name: 본문에 나온 표현.
- canonical_name: 온톨로지 정규화 명칭. 해당 없으면 null.
- enforce_date: 법령(regulation)이고 본문에 시행일이 있으면 ISO(YYYY-MM-DD), 없으면 null.
- 본문에 근거가 없는 항목은 만들지 않는다.

[출력 JSON 스키마]
{"entities": [
  {"type": "regulation|product|sector|agency|dept",
   "name": "<문자열>",
   "canonical_name": null,
   "enforce_date": null}
]}
"""
)
