"""Import all models so Alembic and relationship resolution see every table."""

from app.models.account import AnalyticsEvent, AuditLog, Plan, SystemSetting, UserPreferences
from app.models.auth import EmailToken, Session
from app.models.chat import Conversation, Feedback, Message, MessagePart
from app.models.extras import (
    ApiKey,
    Memory,
    Payment,
    PaymentWebhookEvent,
    Subscription,
    ToolCall,
)
from app.models.files import ConversationFile, DataExport, DocumentChunk, File, ModerationFlag
from app.models.usage import UsageDaily, UsageRecord
from app.models.user import User

__all__ = [
    "AnalyticsEvent",
    "ApiKey",
    "AuditLog",
    "Conversation",
    "ConversationFile",
    "DataExport",
    "DocumentChunk",
    "EmailToken",
    "Feedback",
    "File",
    "Memory",
    "Message",
    "MessagePart",
    "ModerationFlag",
    "Payment",
    "PaymentWebhookEvent",
    "Plan",
    "Session",
    "Subscription",
    "SystemSetting",
    "ToolCall",
    "UsageDaily",
    "UsageRecord",
    "User",
    "UserPreferences",
]
