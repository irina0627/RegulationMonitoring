"""SQLAlchemy 모델 패키지.

모든 모델을 여기서 import 해 Base.metadata 에 등록되게 한다.
(Alembic autogenerate 및 metadata.create_all 이 전체 테이블을 인식하도록)
"""

from app.models.delivery_log import DeliveryLog
from app.models.entity import Entity
from app.models.issue import Issue
from app.models.issue_entity import IssueEntity
from app.models.issue_source import IssueSource
from app.models.news_article import NewsArticle
from app.models.press_release import PressRelease
from app.models.recipient import Recipient
from app.models.recipient_group import RecipientGroup
from app.models.regulation_detail import RegulationDetail

__all__ = [
    "PressRelease",
    "Issue",
    "Entity",
    "IssueSource",
    "IssueEntity",
    "NewsArticle",
    "RegulationDetail",
    "RecipientGroup",
    "Recipient",
    "DeliveryLog",
]
