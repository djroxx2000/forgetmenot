# HTTP API

FastAPI-based HTTP server exposing forgetmenot's memory operations. Interactive docs available at `/docs` when running.

## Running

```bash
python -m forgetmenot.api.server
```

Default: `http://localhost:8230`. Configure via `FORGETMENOT_API_HOST` and `FORGETMENOT_API_PORT`.

## Startup Lifecycle

The app uses FastAPI's lifespan pattern to initialize and tear down resources:

1. Load settings from environment / `.env`
2. Discover and register source engines via `EngineRegistry`
3. Initialize `ArchiveStore` and create database tables
4. Initialize `MemoryEngine` (Mem0 wrapper)
5. Initialize `DedupFilter`
6. On shutdown: dispose database connections

All components are stored on `app.state` and accessed by route handlers via `request.app.state`.

## Endpoints

All endpoints are prefixed with `/api/v1`.

### `POST /api/v1/memories` -- Ingest a Conversation

Runs the full pipeline: normalize, archive raw data, extract facts via Mem0.

**Request body**:

```json
{
  "source": "cursor",
  "session_id": "unique-session-id",
  "conversation": [
    {"role": "user", "content": "How should we handle auth?"},
    {"role": "assistant", "content": "JWT with refresh tokens..."},
    {"role": "user", "content": "What about session storage?"}
  ],
  "metadata": {
    "project": "myapp",
    "workspace": "/path/to/project",
    "model": "claude-4-sonnet",
    "domain_tags": ["auth", "architecture"]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | Origin: `cursor`, `cli`, `browser`, `api` |
| `session_id` | string | yes | Unique session identifier |
| `conversation` | array | yes | Messages with `role` and `content` |
| `metadata.project` | string | no | Project name |
| `metadata.workspace` | string | no | Workspace/repo path |
| `metadata.model` | string | no | LLM model used |
| `metadata.domain_tags` | string[] | no | Topic tags for filtering |

**Response** (`200`):

```json
{
  "status": "ok",
  "session_id": "unique-session-id",
  "artifacts_count": 3,
  "mem0_result": {
    "results": [{"id": "...", "memory": "...", "event": "ADD"}],
    "relations": {"added_entities": [...]}
  }
}
```

**Error** (`400`): returned if the conversation produces no artifacts (e.g., empty message list).

### `GET /api/v1/memories/search` -- Semantic Search

Search extracted memories with dedup filtering.

**Query parameters**:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | (required) | Natural language search query |
| `user_id` | string | `"default"` | User ID to search |
| `limit` | int | `10` | Max results (1-100) |
| `exclude_session_id` | string | `null` | Session ID to exclude (echo prevention) |

**Example**:

```bash
curl "http://localhost:8230/api/v1/memories/search?q=database+architecture&limit=5"
```

**Response** (`200`):

```json
{
  "results": [
    {
      "id": "abc123",
      "memory": "Prefers PostgreSQL with pgvector for vector storage",
      "score": 0.87,
      "metadata": {"project": "forgetmenot", "session_id": "..."},
      "created_at": "2026-04-09T10:00:00Z",
      "updated_at": null
    }
  ],
  "query": "database architecture",
  "total": 1
}
```

### `GET /api/v1/memories/sessions` -- List Sessions

List all archived conversation sessions, ordered by most recent first.

**Response** (`200`):

```json
{
  "sessions": [
    {
      "session_id": "abc-123",
      "source": "cursor",
      "message_count": 12,
      "project": "forgetmenot",
      "created_at": "2026-04-09T10:00:00Z"
    }
  ]
}
```

### `GET /api/v1/memories/{memory_id}` -- Get Memory

Retrieve a specific extracted memory by its Mem0 ID.

**Response** (`200`):

```json
{
  "id": "abc123",
  "memory": "Uses Qdrant for vector storage in forgetmenot",
  "metadata": {"session_id": "...", "project": "forgetmenot"},
  "created_at": "2026-04-09T10:00:00Z",
  "updated_at": null
}
```

**Error** (`404`): memory not found.

### `DELETE /api/v1/memories/{memory_id}` -- Delete Memory

Delete a specific memory from Mem0 (Qdrant + Neo4j). Does not affect the raw archive in PostgreSQL.

**Response** (`200`):

```json
{"status": "deleted", "id": "abc123"}
```

### `GET /api/v1/archive/{session_id}` -- Get Raw Archive

Retrieve the verbatim raw conversation archive for a session from PostgreSQL.

**Response** (`200`):

```json
[
  {
    "session_id": "abc-123",
    "source": "cursor",
    "raw_json": "{\"source\":\"cursor\",\"conversation\":[...]}",
    "message_count": 12,
    "project": "forgetmenot",
    "workspace": "/path/to/project",
    "created_at": "2026-04-09T10:00:00Z"
  }
]
```

**Error** (`404`): no archive found for the session.

### `GET /api/v1/health` -- Health Check

Probes all three infrastructure services and reports status.

**Response** (`200`):

```json
{
  "status": "ok",
  "services": {
    "qdrant": "healthy",
    "neo4j": "healthy",
    "postgres": "healthy"
  }
}
```

`status` is `"ok"` if all services are healthy, `"degraded"` otherwise. Individual services report `"healthy"`, `"unhealthy"`, or `"unreachable"`.

## Schemas

Request/response models are defined in `schemas.py` using Pydantic. These serve as API-boundary DTOs, separate from the internal models in `models/`.
