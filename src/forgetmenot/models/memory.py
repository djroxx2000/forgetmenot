from datetime import datetime

from pydantic import BaseModel, Field


class MemoryResult(BaseModel):
    """Single memory returned from a search."""

    id: str
    memory: str
    score: float | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchResults(BaseModel):
    """Collection of search results with metadata."""

    results: list[MemoryResult] = Field(default_factory=list)
    query: str
    total: int = 0
