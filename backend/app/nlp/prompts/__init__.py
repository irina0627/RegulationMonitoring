"""작업별 프롬프트 템플릿 (설계서 12.2).

4개 작업의 system 프롬프트를 노출한다. 출력은 각 프롬프트에 명시된 JSON 스키마로 강제.
"""

from app.nlp.prompts.entities import ENTITIES_SYSTEM
from app.nlp.prompts.impact import IMPACT_SYSTEM
from app.nlp.prompts.lifecycle import LIFECYCLE_SYSTEM
from app.nlp.prompts.summarize import SUMMARIZE_SYSTEM

__all__ = [
    "SUMMARIZE_SYSTEM",
    "ENTITIES_SYSTEM",
    "LIFECYCLE_SYSTEM",
    "IMPACT_SYSTEM",
]
