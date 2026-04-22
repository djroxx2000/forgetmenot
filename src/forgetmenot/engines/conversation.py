import json
import logging
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from forgetmenot.engines.base import ArchiveBase, SourceEngine
from forgetmenot.models.artifact import MemoryArtifact
from forgetmenot.models.conversation import ConversationPayload

logger = logging.getLogger(__name__)


class ConversationArchive(ArchiveBase):
    """Raw archive table for conversation data."""

    __tablename__ = "conversation_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))
    raw_json: Mapped[str] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer)
    project: Mapped[str | None] = mapped_column(String(256), nullable=True)
    workspace: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationEngine(SourceEngine):
    """Normalizes multi-format conversations into MemoryArtifacts.

    Supports:
    - Standard message lists (OpenAI/Anthropic format)
    - Cursor JSONL transcripts
    - Raw text (treated as a single user message)
    """

    engine_type = "conversation"

    def normalize(self, raw_input: dict) -> list[MemoryArtifact]:
        payload = ConversationPayload.model_validate(raw_input)
        artifacts: list[MemoryArtifact] = []

        messages = payload.conversation
        if not messages:
            return artifacts

        tags = list(payload.metadata.domain_tags)
        base_meta = {
            k: v
            for k, v in {
                "project": payload.metadata.project,
                "workspace": payload.metadata.workspace,
                "model": payload.metadata.model,
            }.items()
            if v is not None
        }

        for msg in messages:
            artifact = MemoryArtifact(
                engine_type=self.engine_type,
                source=payload.source,
                session_id=payload.session_id,
                content=msg.content,
                content_type="dialogue",
                metadata={**base_meta, "role": msg.role},
                timestamp=msg.timestamp or payload.timestamp,
                tags=tags,
            )
            artifacts.append(artifact)

        return artifacts

    def extract_for_mem0(self, artifacts: list[MemoryArtifact]) -> list[dict]:
        """Format artifacts as Mem0-compatible message lists.

        Groups all artifacts from the same session into a single conversation
        for Mem0 to extract facts from holistically.
        """
        sessions: dict[str, list[MemoryArtifact]] = {}
        for art in artifacts:
            sessions.setdefault(art.session_id, []).append(art)

        results = []
        for session_id, session_artifacts in sessions.items():
            session_artifacts.sort(key=lambda a: a.timestamp)
            messages = [
                {"role": a.metadata.get("role", "user"), "content": a.content}
                for a in session_artifacts
            ]
            results.append({
                "messages": messages,
                "user_id": "default",
                "metadata": {
                    "session_id": session_id,
                    "engine_type": self.engine_type,
                    "source": session_artifacts[0].source,
                    **{k: v for k, v in session_artifacts[0].metadata.items() if k != "role"},
                },
            })

        return results

    def archive_schema(self) -> type[ArchiveBase]:
        return ConversationArchive

    def prepare_archive_record(
        self, raw_input: dict, payload: ConversationPayload | None = None
    ) -> ConversationArchive:
        """Create a ConversationArchive record from raw input."""
        if payload is None:
            payload = ConversationPayload.model_validate(raw_input)

        return ConversationArchive(
            session_id=payload.session_id,
            source=payload.source,
            raw_json=json.dumps(raw_input, default=str),
            message_count=len(payload.conversation),
            project=payload.metadata.project,
            workspace=payload.metadata.workspace,
            created_at=payload.timestamp,
        )


def normalize_cursor_jsonl(jsonl_content: str) -> dict:
    """Convert a Cursor JSONL transcript into the standard conversation payload format."""
    messages = []
    for line in jsonl_content.strip().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSONL line")
            continue

        role = entry.get("role", "user")
        content = entry.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )

        if content.strip():
            ts = entry.get("timestamp")
            messages.append({"role": role, "content": content, **({"timestamp": ts} if ts else {})})

    return {
        "source": "cursor",
        "session_id": "",
        "conversation": messages,
        "metadata": {},
    }


def normalize_raw_text(text: str, source: str = "api") -> dict:
    """Wrap raw text as a single-message conversation payload."""
    return {
        "source": source,
        "session_id": "",
        "conversation": [{"role": "user", "content": text}],
        "metadata": {},
    }
