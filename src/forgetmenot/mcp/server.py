"""MCP server for forgetmenot: memory_save, memory_recall, memory_list_sessions.

Runs over stdio transport for Cursor integration.
"""

import asyncio
import json
import logging
import time
import uuid

from mcp.server.fastmcp import Context, FastMCP

from forgetmenot.config import get_settings
from forgetmenot.core.archive import ArchiveStore
from forgetmenot.core.dedup import DedupFilter
from forgetmenot.core.engine_registry import EngineRegistry
from forgetmenot.core.memory_engine import MemoryEngine

logger = logging.getLogger(__name__)

mcp = FastMCP("forgetmenot", instructions="Persistent AI memory service. Save and recall memories across sessions.")

_memory_engine: MemoryEngine | None = None
_archive: ArchiveStore | None = None
_registry: EngineRegistry | None = None
_dedup: DedupFilter | None = None


def _prewarm_ollama(settings) -> None:
    """Send a lightweight request to Ollama to pre-load models into memory."""
    import httpx

    base = settings.ollama_base_url
    for model in {settings.embedding_model, settings.mem0_llm_model}:
        try:
            httpx.post(
                f"{base}/api/embed",
                json={"model": model, "input": "warmup"},
                timeout=30,
            )
            logger.info("Pre-warmed Ollama model: %s", model)
        except Exception as exc:
            logger.warning("Failed to pre-warm model %s: %s", model, exc)


def _get_components() -> tuple[MemoryEngine, ArchiveStore, EngineRegistry, DedupFilter]:
    global _memory_engine, _archive, _registry, _dedup

    if _memory_engine is None:
        settings = get_settings()

        _registry = EngineRegistry()
        _registry.discover()

        _memory_engine = MemoryEngine(settings)

        _archive = ArchiveStore(settings)

        _dedup = DedupFilter(settings)

        _prewarm_ollama(settings)

    assert _memory_engine is not None
    assert _archive is not None
    assert _registry is not None
    assert _dedup is not None
    return _memory_engine, _archive, _registry, _dedup


@mcp.tool()
async def memory_save(
    conversation: str,
    source: str = "cursor",
    session_id: str = "",
    project: str = "",
    workspace: str = "",
    domain_tags: str = "",
    ctx: Context | None = None,
) -> str:
    """Save a conversation to forgetmenot's persistent memory.

    Args:
        conversation: The conversation content as a JSON array of messages
                      (each with "role" and "content" keys) or as plain text.
        source: Where the conversation came from (cursor, cli, browser, api).
        session_id: Unique identifier for this session. Auto-generated if empty.
        project: Project name for metadata.
        workspace: Workspace path for metadata.
        domain_tags: Comma-separated domain tags (e.g. "python,rag,architecture").
    """
    t_total = time.perf_counter()
    timing: dict[str, float] = {}
    memory_engine, archive, registry, _ = _get_components()

    if ctx:
        await ctx.report_progress(0, 100)

    if not session_id:
        session_id = str(uuid.uuid4())

    t0 = time.perf_counter()
    try:
        messages = json.loads(conversation)
        if not isinstance(messages, list):
            messages = [{"role": "user", "content": conversation}]
    except json.JSONDecodeError:
        messages = [{"role": "user", "content": conversation}]

    tags = [t.strip() for t in domain_tags.split(",") if t.strip()] if domain_tags else []

    raw_input = {
        "source": source,
        "session_id": session_id,
        "conversation": messages,
        "metadata": {
            "project": project or None,
            "workspace": workspace or None,
            "domain_tags": tags,
        },
    }

    engine = registry.get("conversation")
    artifacts = engine.normalize(raw_input)
    timing["parse"] = round((time.perf_counter() - t0) * 1000, 1)

    if ctx:
        await ctx.report_progress(10, 100)

    t0 = time.perf_counter()
    archive_record = engine.prepare_archive_record(raw_input)
    await archive.init_tables()
    await archive.save(archive_record)
    timing["archive"] = round((time.perf_counter() - t0) * 1000, 1)

    if ctx:
        await ctx.report_progress(20, 100)

    mem0_payloads = engine.extract_for_mem0(artifacts)
    t0 = time.perf_counter()

    async def _add_payload(payload):
        return await asyncio.to_thread(
            memory_engine.add,
            messages=payload["messages"],
            user_id=payload.get("user_id", "default"),
            metadata=payload.get("metadata"),
        )

    try:
        results = await asyncio.gather(
            *[_add_payload(p) for p in mem0_payloads],
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, ConnectionError)]
        if errors:
            raise errors[0]
        results = [r for r in results if not isinstance(r, BaseException)]
    except ConnectionError as exc:
        logger.error("Ollama connection failed during memory_save: %s", exc)
        return json.dumps({
            "status": "error",
            "message": str(exc),
            "session_id": session_id,
            "artifacts_count": len(artifacts),
        })
    timing["mem0_add"] = round((time.perf_counter() - t0) * 1000, 1)

    if ctx:
        await ctx.report_progress(90, 100)

    timing["total"] = round((time.perf_counter() - t_total) * 1000, 1)

    if ctx:
        await ctx.report_progress(100, 100)

    return json.dumps({
        "status": "saved",
        "session_id": session_id,
        "artifacts_count": len(artifacts),
        "mem0_results": results,
        "timing_ms": timing,
    }, default=str)


@mcp.tool()
async def memory_recall(
    query: str,
    user_id: str = "default",
    limit: int = 10,
    exclude_session_id: str = "",
    ctx: Context | None = None,
) -> str:
    """Search forgetmenot's persistent memory for relevant information.

    Args:
        query: Natural language search query.
        user_id: User ID to search memories for.
        limit: Maximum number of results to return.
        exclude_session_id: Session ID to exclude from results (prevents echo).
    """
    t_total = time.perf_counter()
    timing: dict[str, float] = {}
    memory_engine, _, _, dedup = _get_components()

    if ctx:
        await ctx.report_progress(0, 100)

    try:
        raw_results = await asyncio.to_thread(
            memory_engine.search, query=query, user_id=user_id, limit=limit,
        )
    except ConnectionError as exc:
        logger.error("Ollama connection failed during memory_recall: %s", exc)
        return json.dumps({
            "status": "error",
            "message": str(exc),
            "query": query,
        })
    engine_timing = raw_results.pop("timing_ms", {})
    timing.update(engine_timing)
    results_list = raw_results.get("results", [])

    if ctx:
        await ctx.report_progress(80, 100)

    t0 = time.perf_counter()
    filtered = dedup.filter(
        results_list,
        exclude_session_id=exclude_session_id or None,
    )
    timing["dedup"] = round((time.perf_counter() - t0) * 1000, 1)

    timing["total"] = round((time.perf_counter() - t_total) * 1000, 1)

    if ctx:
        await ctx.report_progress(100, 100)

    return json.dumps({
        "query": query,
        "total": len(filtered),
        "results": [r.model_dump(mode="json") for r in filtered],
        "timing_ms": timing,
    }, default=str)


@mcp.tool()
async def memory_list_sessions(limit: int = 20) -> str:
    """List recent memory sessions with metadata.

    Args:
        limit: Maximum number of sessions to return.
    """
    _, archive, _, _ = _get_components()

    from sqlalchemy import select

    from forgetmenot.engines.conversation import ConversationArchive

    await archive.init_tables()
    async with archive._session_factory() as sess:
        stmt = (
            select(ConversationArchive)
            .order_by(ConversationArchive.created_at.desc())
            .limit(limit)
        )
        result = await sess.execute(stmt)
        records = result.scalars().all()

    sessions = [
        {
            "session_id": r.session_id,
            "source": r.source,
            "message_count": r.message_count,
            "project": r.project,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]

    return json.dumps({"sessions": sessions, "total": len(sessions)}, default=str)


@mcp.tool()
async def memory_delete(memory_id: str) -> str:
    """Delete a specific memory from forgetmenot by its ID.

    Use memory_recall first to find the ID of the memory you want to remove,
    then pass it here.

    Args:
        memory_id: ID of the memory to delete.
    """
    memory_engine, _, _, _ = _get_components()

    try:
        result = await asyncio.to_thread(memory_engine.delete, memory_id)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

    return json.dumps({"status": "deleted", "memory_id": memory_id, "result": result}, default=str)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Starting forgetmenot MCP server (stdio)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
