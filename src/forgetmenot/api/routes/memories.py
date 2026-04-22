import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from forgetmenot.api.schemas import (
    ArchiveOut,
    DeleteResponse,
    IngestRequest,
    IngestResponse,
    MemoryDetailResponse,
    MemoryResultOut,
    SearchResponse,
    SessionListResponse,
    SessionOut,
)
from forgetmenot.engines.conversation import ConversationArchive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memories")


@router.post("", response_model=IngestResponse)
async def ingest_memory(request: Request, body: IngestRequest) -> IngestResponse:
    """Ingest a conversation: archive raw data + extract facts via Mem0."""
    t_total = time.perf_counter()
    timing: dict[str, float] = {}
    registry = request.app.state.engine_registry
    memory_engine = request.app.state.memory_engine
    archive = request.app.state.archive

    t0 = time.perf_counter()
    raw_input = body.model_dump(mode="json")
    engine = registry.get("conversation")

    artifacts = engine.normalize(raw_input)
    if not artifacts:
        raise HTTPException(status_code=400, detail="No artifacts produced from input")
    timing["parse"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    archive_record = engine.prepare_archive_record(raw_input)
    await archive.save(archive_record)
    timing["archive"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    mem0_payloads = engine.extract_for_mem0(artifacts)
    mem0_result: dict = {}
    for payload in mem0_payloads:
        result = await asyncio.to_thread(
            memory_engine.add,
            messages=payload["messages"],
            user_id=payload.get("user_id", "default"),
            metadata=payload.get("metadata"),
        )
        mem0_result = result
    timing["mem0_add"] = round((time.perf_counter() - t0) * 1000, 1)

    timing["total"] = round((time.perf_counter() - t_total) * 1000, 1)

    return IngestResponse(
        session_id=body.session_id,
        artifacts_count=len(artifacts),
        mem0_result=mem0_result,
        timing_ms=timing,
    )


@router.get("/search", response_model=SearchResponse)
async def search_memories(
    request: Request,
    q: str = Query(..., description="Search query"),
    user_id: str = Query("default"),
    limit: int = Query(10, ge=1, le=100),
    exclude_session_id: str | None = Query(None),
) -> SearchResponse:
    """Semantic search over extracted memories with dedup filtering."""
    t_total = time.perf_counter()
    timing: dict[str, float] = {}
    memory_engine = request.app.state.memory_engine
    dedup = request.app.state.dedup_filter

    raw_results = await asyncio.to_thread(memory_engine.search, query=q, user_id=user_id, limit=limit)
    engine_timing = raw_results.pop("timing_ms", {})
    timing.update(engine_timing)
    results_list = raw_results.get("results", [])

    t0 = time.perf_counter()
    filtered = dedup.filter(results_list, exclude_session_id=exclude_session_id)
    timing["dedup"] = round((time.perf_counter() - t0) * 1000, 1)

    timing["total"] = round((time.perf_counter() - t_total) * 1000, 1)

    return SearchResponse(
        results=[MemoryResultOut(**r.model_dump()) for r in filtered],
        query=q,
        total=len(filtered),
        timing_ms=timing,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    """List all archived conversation sessions."""
    archive = request.app.state.archive

    async with archive._session_factory() as sess:
        stmt = select(ConversationArchive).order_by(ConversationArchive.created_at.desc())
        result = await sess.execute(stmt)
        records = result.scalars().all()

    sessions = [
        SessionOut(
            session_id=r.session_id,
            source=r.source,
            message_count=r.message_count,
            project=r.project,
            created_at=r.created_at,
        )
        for r in records
    ]
    return SessionListResponse(sessions=sessions)


@router.get("/{memory_id}", response_model=MemoryDetailResponse)
async def get_memory(request: Request, memory_id: str) -> MemoryDetailResponse:
    """Get a specific memory by ID."""
    memory_engine = request.app.state.memory_engine

    try:
        result = await asyncio.to_thread(memory_engine.get, memory_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return MemoryDetailResponse(
        id=result.get("id", memory_id),
        memory=result.get("memory", ""),
        metadata=result.get("metadata", {}),
        created_at=result.get("created_at"),
        updated_at=result.get("updated_at"),
    )


@router.delete("/{memory_id}", response_model=DeleteResponse)
async def delete_memory(request: Request, memory_id: str) -> DeleteResponse:
    """Delete a specific memory."""
    memory_engine = request.app.state.memory_engine

    try:
        await asyncio.to_thread(memory_engine.delete, memory_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return DeleteResponse(id=memory_id)


@router.get("/archive/{session_id}", response_model=list[ArchiveOut])
async def get_archive(request: Request, session_id: str) -> list[ArchiveOut]:
    """Retrieve the raw conversation archive for a session."""
    archive = request.app.state.archive

    records = await archive.query_by_session(ConversationArchive, session_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"No archive found for session {session_id}")

    return [
        ArchiveOut(
            session_id=r.session_id,
            source=r.source,
            raw_json=r.raw_json,
            message_count=r.message_count,
            project=r.project,
            workspace=r.workspace,
            created_at=r.created_at,
        )
        for r in records
    ]
