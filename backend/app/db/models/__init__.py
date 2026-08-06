"""Import every model module so SQLAlchemy's declarative registry sees all
tables before Base.metadata.create_all() runs (see db/session.py:init_db)."""
from app.db.models.ai import (  # noqa: F401
    AIAnalysis,
    AnalysisQueueItem,
    AuditLogEntry,
    ClassificationFeedback,
    PromptTemplate,
    PromptVersion,
    TokenUsageLog,
)
from app.db.models.app_settings import AppSettings  # noqa: F401
from app.db.models.company import Company, Contact  # noqa: F401
from app.db.models.deal import Candidate, Deal, MatchScore  # noqa: F401
from app.db.models.email import Attachment, EmailAccount, Message, Thread  # noqa: F401
from app.db.models.meeting import Meeting  # noqa: F401
from app.db.models.plugin import PluginConfig  # noqa: F401
from app.db.models.rule import Rule  # noqa: F401
from app.db.models.tag import MessageTag, Tag  # noqa: F401

__all__ = [
    "AIAnalysis",
    "AnalysisQueueItem",
    "AuditLogEntry",
    "ClassificationFeedback",
    "PromptTemplate",
    "PromptVersion",
    "TokenUsageLog",
    "AppSettings",
    "Company",
    "Contact",
    "Candidate",
    "Deal",
    "MatchScore",
    "Attachment",
    "EmailAccount",
    "Message",
    "Thread",
    "Meeting",
    "PluginConfig",
    "Rule",
    "MessageTag",
    "Tag",
]
