"""Integration tests for the forgetmenot pipeline.

Tests the full flow: ingest via API -> raw archive stored -> Mem0 facts extracted -> search with dedup.
Requires running infrastructure (Qdrant, Neo4j, Postgres, Ollama).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from forgetmenot.api.server import create_app
from forgetmenot.config import Settings


def _test_settings() -> Settings:
    return Settings(
        postgres_dsn="postgresql+asyncpg://memzero:memzero_dev@localhost:5432/memzero",
        qdrant_host="localhost",
        qdrant_port=6333,
        neo4j_url="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="memzero_dev",
        debug=True,
    )


@pytest.fixture
async def client():
    settings = _test_settings()
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "qdrant" in data["services"]
    assert "neo4j" in data["services"]
    assert "postgres" in data["services"]


@pytest.mark.asyncio
async def test_ingest_and_search(client: AsyncClient):
    session_id = str(uuid.uuid4())

    ingest_payload = {
        "source": "api",
        "session_id": session_id,
        "conversation": [
            {"role": "user", "content": "I prefer using Python with FastAPI for building REST APIs."},
            {"role": "assistant", "content": "Noted! FastAPI is a great choice for Python REST APIs."},
            {"role": "user", "content": "I always use PostgreSQL as my primary database and Qdrant for vector search."},
            {"role": "assistant", "content": "PostgreSQL + Qdrant is a solid combination."},
        ],
        "metadata": {
            "project": "forgetmenot-test",
            "workspace": "/tmp/test",
            "domain_tags": ["python", "fastapi", "databases"],
        },
    }

    resp = await client.post("/api/v1/memories", json=ingest_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["session_id"] == session_id
    assert data["artifacts_count"] == 4

    resp = await client.get("/api/v1/memories/search", params={"q": "What database does the user prefer?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "What database does the user prefer?"
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_archive_retrieval(client: AsyncClient):
    session_id = str(uuid.uuid4())

    ingest_payload = {
        "source": "cursor",
        "session_id": session_id,
        "conversation": [
            {"role": "user", "content": "Remember that my favorite editor is Cursor."},
            {"role": "assistant", "content": "Got it, you prefer Cursor as your editor."},
        ],
        "metadata": {"project": "test-archive"},
    }

    await client.post("/api/v1/memories", json=ingest_payload)

    resp = await client.get(f"/api/v1/archive/{session_id}")
    assert resp.status_code == 200
    archives = resp.json()
    assert len(archives) >= 1
    assert archives[0]["session_id"] == session_id
    assert archives[0]["source"] == "cursor"
    assert archives[0]["message_count"] == 2


@pytest.mark.asyncio
async def test_session_list(client: AsyncClient):
    resp = await client.get("/api/v1/memories/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.asyncio
async def test_search_with_session_exclusion(client: AsyncClient):
    session_id = str(uuid.uuid4())

    ingest_payload = {
        "source": "api",
        "session_id": session_id,
        "conversation": [
            {"role": "user", "content": "I am testing dedup filters with unique session IDs."},
        ],
        "metadata": {"project": "test-dedup"},
    }

    await client.post("/api/v1/memories", json=ingest_payload)

    resp = await client.get(
        "/api/v1/memories/search",
        params={"q": "dedup filters", "exclude_session_id": session_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    for result in data["results"]:
        meta = result.get("metadata", {})
        assert meta.get("session_id") != session_id


@pytest.mark.asyncio
async def test_ingest_empty_conversation(client: AsyncClient):
    payload = {
        "source": "api",
        "session_id": str(uuid.uuid4()),
        "conversation": [],
    }
    resp = await client.post("/api/v1/memories", json=payload)
    assert resp.status_code == 400
