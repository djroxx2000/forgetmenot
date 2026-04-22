import logging

from forgetmenot.config import Settings, get_settings
from forgetmenot.models.memory import MemoryResult

logger = logging.getLogger(__name__)


class DedupFilter:
    """Two-layer echo prevention for memory retrieval.

    1. Session exclusion: exclude memories from the current session
    2. Similarity threshold: skip near-duplicate results (token overlap > threshold)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def filter(
        self,
        results: list[dict],
        *,
        exclude_session_id: str | None = None,
    ) -> list[MemoryResult]:
        """Apply all dedup filters to raw Mem0 search results."""
        filtered: list[MemoryResult] = []
        seen_contents: list[str] = []

        for raw in results:
            memory_text = raw.get("memory", "")
            metadata = raw.get("metadata", {})
            score = raw.get("score")

            if exclude_session_id and metadata.get("session_id") == exclude_session_id:
                logger.debug("Excluding memory from current session: %s", raw.get("id"))
                continue

            if score is not None and score > self._settings.dedup_similarity_threshold:
                if self._is_near_duplicate(memory_text, seen_contents):
                    logger.debug("Excluding near-duplicate memory: %s", raw.get("id"))
                    continue

            seen_contents.append(memory_text)
            filtered.append(MemoryResult(
                id=raw.get("id", ""),
                memory=memory_text,
                score=score,
                metadata=metadata,
                created_at=raw.get("created_at"),
                updated_at=raw.get("updated_at"),
            ))

        logger.info("Dedup filter: %d -> %d results", len(results), len(filtered))
        return filtered

    def _is_near_duplicate(self, text: str, seen: list[str]) -> bool:
        """Simple token-overlap check for near-duplicate detection.

        This is a lightweight client-side check; the heavy lifting
        (vector cosine similarity) is done by Mem0 during add().
        """
        if not seen:
            return False

        text_tokens = set(text.lower().split())
        if not text_tokens:
            return False

        for existing in seen:
            existing_tokens = set(existing.lower().split())
            if not existing_tokens:
                continue
            overlap = len(text_tokens & existing_tokens) / max(len(text_tokens), len(existing_tokens))
            if overlap > self._settings.dedup_similarity_threshold:
                return True
        return False
