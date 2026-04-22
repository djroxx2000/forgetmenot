import logging
import time

from mem0 import Memory

from forgetmenot.config import Settings, get_settings

logger = logging.getLogger(__name__)

_OLLAMA_RETRIES = 3
_OLLAMA_BACKOFF_BASE = 2.0


def _retry_on_connection_error(func, *args, **kwargs):
    """Retry a callable with exponential backoff on connection failures."""
    last_exc: Exception | None = None
    for attempt in range(_OLLAMA_RETRIES):
        try:
            return func(*args, **kwargs)
        except (ConnectionError, OSError) as exc:
            last_exc = exc
            wait = _OLLAMA_BACKOFF_BASE ** attempt
            logger.warning(
                "Ollama connection failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, _OLLAMA_RETRIES, wait, exc,
            )
            time.sleep(wait)
        except Exception as exc:
            if "Connection" in type(exc).__name__ or "connection" in str(exc).lower():
                last_exc = exc
                wait = _OLLAMA_BACKOFF_BASE ** attempt
                logger.warning(
                    "Ollama connection failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _OLLAMA_RETRIES, wait, exc,
                )
                time.sleep(wait)
            else:
                raise
    raise ConnectionError(
        f"Ollama unreachable after {_OLLAMA_RETRIES} attempts. "
        "Is Ollama running? Try: ollama serve"
    ) from last_exc

CUSTOM_INSTRUCTIONS = """You are a Personal Information Organizer. Extract facts and preferences from the conversation.

Focus on extracting:
- User preferences, habits, and workflows
- Technical decisions and their rationale
- Project context: tools, languages, frameworks, architecture patterns
- Recurring problems and their solutions
- Named entities: people, projects, repos, services, APIs
- Explicit requests to remember something

Do NOT extract:
- Transient debugging output or stack traces
- Code snippets without context
- Generic greetings or filler

Return the extracted facts in the following json format: {{"facts": ["fact 1", "fact 2", ...]}}
If no relevant facts are found, return {{"facts": []}}"""


def build_mem0_config(settings: Settings | None = None) -> dict:
    if settings is None:
        settings = get_settings()

    config: dict = {
        "history_db_path": ".mem0/history.db",
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": settings.qdrant_host,
                "port": settings.qdrant_port,
                "collection_name": "forgetmenot",
                "embedding_model_dims": settings.embedding_dims,
            },
        },
        "llm": {
            "provider": settings.mem0_llm_provider,
            "config": {
                "model": settings.mem0_llm_model,
                "temperature": 0.1,
                "max_tokens": 1024,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": settings.embedding_model,
                "ollama_base_url": settings.ollama_base_url,
                "embedding_dims": settings.embedding_dims,
            },
        },
        "custom_fact_extraction_prompt": CUSTOM_INSTRUCTIONS,
    }

    if settings.mem0_llm_provider == "ollama":
        config["llm"]["config"]["ollama_base_url"] = settings.ollama_base_url

    if settings.graph_store_enabled:
        config["graph_store"] = {
            "provider": "neo4j",
            "config": {
                "url": settings.neo4j_url,
                "username": settings.neo4j_user,
                "password": settings.neo4j_password,
            },
        }

    return config


class MemoryEngine:
    """Wraps Mem0 Memory with project-specific configuration."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        config = build_mem0_config(self._settings)
        logger.info("Initializing Mem0 with config: vector_store=%s, llm=%s, embedder=%s, graph_store=%s",
                     config["vector_store"]["provider"],
                     config["llm"]["provider"],
                     config["embedder"]["provider"],
                     config.get("graph_store", {}).get("provider", "none"))
        self._mem0 = Memory.from_config(config)

    @property
    def mem0(self) -> Memory:
        return self._mem0

    def add(self, messages: list[dict], user_id: str = "default", metadata: dict | None = None) -> dict:
        """Add messages to memory via Mem0's extraction pipeline."""
        kwargs: dict = {"user_id": user_id}
        if metadata:
            kwargs["metadata"] = metadata
        t0 = time.perf_counter()
        result = _retry_on_connection_error(self._mem0.add, messages, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        result["timing_ms"] = {"mem0_add": round(elapsed, 1)}
        logger.info("Mem0 add completed in %.1fms: %s", elapsed, result)
        return result

    def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 10,
        filters: dict | None = None,
    ) -> dict:
        """Search memories via Mem0."""
        kwargs: dict = {"user_id": user_id, "limit": limit}
        if filters:
            kwargs["filters"] = filters
        t0 = time.perf_counter()
        result = _retry_on_connection_error(self._mem0.search, query, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        result["timing_ms"] = {"mem0_search": round(elapsed, 1)}
        logger.info("Mem0 search completed in %.1fms", elapsed)
        return result

    def get_all(self, user_id: str = "default") -> dict:
        """Retrieve all memories for a user."""
        return self._mem0.get_all(user_id=user_id)

    def get(self, memory_id: str) -> dict:
        """Get a specific memory by ID."""
        return self._mem0.get(memory_id)

    def delete(self, memory_id: str) -> dict:
        """Delete a specific memory."""
        return self._mem0.delete(memory_id)

    def delete_all(self, user_id: str = "default") -> dict:
        """Delete all memories for a user."""
        return self._mem0.delete_all(user_id=user_id)
