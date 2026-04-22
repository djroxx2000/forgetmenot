from datetime import datetime

from pydantic import BaseModel, Field


class ConversationMessageIn(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None


class ConversationMetadataIn(BaseModel):
    project: str | None = None
    workspace: str | None = None
    model: str | None = None
    domain_tags: list[str] = Field(default_factory=list)


class IngestRequest(BaseModel):
    source: str
    session_id: str
    conversation: list[ConversationMessageIn]
    metadata: ConversationMetadataIn = Field(default_factory=ConversationMetadataIn)


class IngestResponse(BaseModel):
    status: str = "ok"
    session_id: str
    artifacts_count: int
    mem0_result: dict = Field(default_factory=dict)
    timing_ms: dict[str, float] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    user_id: str = "default"
    limit: int = 10
    exclude_session_id: str | None = None
    filters: dict | None = None


class MemoryResultOut(BaseModel):
    id: str
    memory: str
    score: float | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchResponse(BaseModel):
    results: list[MemoryResultOut] = Field(default_factory=list)
    query: str
    total: int = 0
    timing_ms: dict[str, float] = Field(default_factory=dict)


class MemoryDetailResponse(BaseModel):
    id: str
    memory: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeleteResponse(BaseModel):
    status: str = "deleted"
    id: str


class SessionOut(BaseModel):
    session_id: str
    source: str
    message_count: int
    project: str | None = None
    created_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionOut] = Field(default_factory=list)


class ArchiveOut(BaseModel):
    session_id: str
    source: str
    raw_json: str
    message_count: int
    project: str | None = None
    workspace: str | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: str = "ok"
    services: dict = Field(default_factory=dict)
