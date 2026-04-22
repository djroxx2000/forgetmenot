import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class MemoryArtifact(BaseModel):
    """Unit of knowledge produced by any source engine."""

    id: str = ""
    engine_type: str
    source: str
    session_id: str
    content: str
    content_type: str
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if not self.id:
            self.id = self._compute_id()

    def _compute_id(self) -> str:
        payload = json.dumps(
            {"engine_type": self.engine_type, "session_id": self.session_id, "content": self.content},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
