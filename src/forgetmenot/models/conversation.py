from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None


class ConversationMetadata(BaseModel):
    project: str | None = None
    workspace: str | None = None
    model: str | None = None
    domain_tags: list[str] = Field(default_factory=list)


class ConversationPayload(BaseModel):
    """Ingest payload for the ConversationEngine."""

    source: str
    session_id: str
    conversation: list[ConversationMessage]
    metadata: ConversationMetadata = Field(default_factory=ConversationMetadata)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
