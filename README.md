# Forgetmenot

Persistent AI memory service with pluggable source engines. Wraps [Mem0](https://github.com/mem0ai/mem0) as the core memory engine, stores both raw conversation archives (PostgreSQL) and LLM-extracted facts (Qdrant vectors + Neo4j knowledge graph), exposed via HTTP API and MCP server.

## Architecture

```
  Capture Clients                          Forgetmenot Service
 ┌──────────────┐          ┌─────────────────────────────────────────────────┐
 │ Cursor (MCP) │──stdio──▶│  MCP Server                                    │
 │ CLI tool     │──http───▶│  FastAPI HTTP Server                           │
 │ Browser ext  │──http───▶│                                                │
 │ Any client   │──http───▶│    ┌──────────────────────────────────────┐    │
 └──────────────┘          │    │ Engine Registry                      │    │
                           │    │  ┌─────────────────────────────────┐ │    │
                           │    │  │ ConversationEngine (v0.1)       │ │    │
                           │    │  │ CodebaseEngine    (planned)     │ │    │
                           │    │  │ WebEngine         (planned)     │ │    │
                           │    │  └─────────────────────────────────┘ │    │
                           │    └──────────────┬───────────────────────┘    │
                           │                   │ MemoryArtifacts            │
                           │         ┌─────────┴──────────┐                │
                           │         ▼                    ▼                │
                           │    ┌──────────┐     ┌──────────────┐          │
                           │    │ Archive  │     │ Mem0 Engine  │          │
                           │    │ Store    │     │ (extraction) │          │
                           │    └────┬─────┘     └──┬───────┬───┘          │
                           │         │              │       │              │
                           └─────────┼──────────────┼───────┼──────────────┘
                                     │              │       │
                           ┌─────────▼──┐  ┌───────▼──┐ ┌──▼──────┐
                           │ PostgreSQL  │  │ Qdrant   │ │ Neo4j   │
                           │ (raw store) │  │ (vectors)│ │ (graph) │
                           └────────────┘  └──────────┘ └─────────┘
```

Every conversation is stored **twice**:

1. **Raw archive** in PostgreSQL -- verbatim messages, zero information loss, can be reprocessed with better models later.
2. **Extracted facts** in Qdrant (vector embeddings for semantic search) + Neo4j (knowledge graph for entity relationships) via Mem0's LLM-driven extraction pipeline.

The system uses a **pluggable source engine** architecture. Each engine knows how to ingest a specific data type (conversations, codebases, web pages) and normalize it into `MemoryArtifact` objects. v0.1 ships with `ConversationEngine`; additional engines slot in without modifying the core.

## Prerequisites

- **Docker** and **Docker Compose** (for Qdrant, Neo4j, PostgreSQL)
- **Python >= 3.12**
- **Ollama** running locally with embedding and LLM models pulled

## Quick Start

### 1. Start infrastructure

```bash
./scripts/setup_infra.sh
```

Starts Qdrant (port 6333), Neo4j (ports 7474/7687), and PostgreSQL (port 5432) via Docker Compose with health checks. Waits up to 120 seconds for all services to report healthy.

### 2. Pull Ollama models

The service requires two models -- one for embeddings, one for fact extraction:

```bash
ollama pull embeddinggemma     # embeddings (default)
ollama pull phi4-mini           # LLM for Mem0 fact extraction (default)
```

You can use different models by setting `FORGETMENOT_EMBEDDING_MODEL` and `FORGETMENOT_MEM0_LLM_MODEL` in your `.env` file. Any Ollama-compatible embedding and chat model works.

### 3. Install and configure

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env if you need to change any defaults
```

### 4. Run the HTTP API

```bash
python -m forgetmenot.api.server
```

The API is available at `http://localhost:8230`. Interactive docs at `http://localhost:8230/docs`.

### 5. Run the MCP server (for Cursor)

Add to your Cursor MCP configuration:

```json
{
  "mcpServers": {
    "forgetmenot": {
      "command": "/path/to/forgetmenot/.venv/bin/python",
      "args": ["-m", "forgetmenot.mcp.server"],
      "cwd": "/path/to/forgetmenot"
    }
  }
}
```

Replace the paths with the actual location of your forgetmenot installation.

## Configuration

All settings are controlled via environment variables prefixed with `FORGETMENOT_`, loaded from `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGETMENOT_POSTGRES_DSN` | `postgresql+asyncpg://memzero:memzero_dev@localhost:5432/memzero` | Async PostgreSQL connection string |
| `FORGETMENOT_QDRANT_HOST` | `localhost` | Qdrant server host |
| `FORGETMENOT_QDRANT_PORT` | `6333` | Qdrant server port |
| `FORGETMENOT_NEO4J_URL` | `bolt://localhost:7687` | Neo4j Bolt connection URL |
| `FORGETMENOT_NEO4J_USER` | `neo4j` | Neo4j username |
| `FORGETMENOT_NEO4J_PASSWORD` | `memzero_dev` | Neo4j password |
| `FORGETMENOT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `FORGETMENOT_EMBEDDING_MODEL` | `embeddinggemma` | Ollama embedding model name |
| `FORGETMENOT_EMBEDDING_DIMS` | `768` | Embedding vector dimensions (must match model) |
| `FORGETMENOT_MEM0_LLM_PROVIDER` | `ollama` | LLM provider for Mem0 fact extraction |
| `FORGETMENOT_MEM0_LLM_MODEL` | `phi4-mini` | LLM model for fact extraction |
| `FORGETMENOT_GRAPH_STORE_ENABLED` | `false` | Enable Neo4j knowledge graph (adds ~25s to saves, ~5.5s to searches) |
| `FORGETMENOT_DEDUP_SIMILARITY_THRESHOLD` | `0.95` | Token-overlap threshold for near-duplicate filtering |
| `FORGETMENOT_API_HOST` | `0.0.0.0` | HTTP API bind host |
| `FORGETMENOT_API_PORT` | `8230` | HTTP API bind port |
| `FORGETMENOT_DEBUG` | `false` | Enable debug logging |

## HTTP API

Base URL: `http://localhost:8230/api/v1`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/memories` | Ingest a conversation (archive + extract facts) |
| `GET` | `/memories/search?q=...` | Semantic search with dedup filtering |
| `GET` | `/memories/{id}` | Get a specific extracted memory |
| `DELETE` | `/memories/{id}` | Delete a specific memory |
| `GET` | `/memories/sessions` | List archived sessions |
| `GET` | `/memories/archive/{session_id}` | Retrieve raw conversation archive |
| `GET` | `/health` | Health check (probes Qdrant, Neo4j, PostgreSQL) |

### Example: Ingest a conversation

```bash
curl -X POST http://localhost:8230/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "source": "api",
    "session_id": "test-001",
    "conversation": [
      {"role": "user", "content": "How should we structure the database schema?"},
      {"role": "assistant", "content": "I recommend using PostgreSQL with separate tables per domain..."}
    ],
    "metadata": {
      "project": "myproject",
      "domain_tags": ["database", "architecture"]
    }
  }'
```

### Example: Search memories

```bash
curl "http://localhost:8230/api/v1/memories/search?q=database+schema&limit=5"
```

## MCP Tools

When connected via MCP (e.g., from Cursor), the following tools are available:

| Tool | Description |
|------|-------------|
| `memory_save` | Save a conversation to persistent memory. Accepts JSON message array or plain text. Archives raw data to PostgreSQL and extracts facts via Mem0. |
| `memory_recall` | Search memories by natural language query. Returns semantically relevant results with dedup filtering (session exclusion + near-duplicate removal). |
| `memory_list_sessions` | List recent memory sessions with metadata (source, message count, project, timestamps). |
| `memory_delete` | Delete a specific memory by ID. Use `memory_recall` first to find the ID. |

## Echo Prevention

The dedup filter prevents the echo chamber problem (retrieving what you just saved) with two layers:

1. **Session exclusion**: pass `exclude_session_id` to filter out memories from the current session.
2. **Near-duplicate detection**: token-overlap (Jaccard similarity) check against results already in the response. Configurable threshold via `FORGETMENOT_DEDUP_SIMILARITY_THRESHOLD`.

Mem0 itself also handles dedup during ingestion -- it compares new facts against existing ones and decides whether to add, update, or skip.

## Project Structure

```
forgetmenot/
├── docker-compose.yml              # Qdrant + Neo4j + PostgreSQL
├── pyproject.toml                  # Dependencies, build config, linting
├── .env.example                    # Environment variable template
├── scripts/
│   └── setup_infra.sh              # Start + health-check infrastructure
├── src/forgetmenot/
│   ├── config.py                   # Pydantic settings (all FORGETMENOT_* env vars)
│   ├── engines/                    # Pluggable source engines
│   │   ├── base.py                 # SourceEngine ABC + ArchiveBase
│   │   └── conversation.py         # ConversationEngine (v0.1)
│   ├── core/                       # Processing pipeline
│   │   ├── engine_registry.py      # Auto-discovers + manages engines
│   │   ├── memory_engine.py        # Mem0 wrapper with retry logic
│   │   ├── archive.py              # Async PostgreSQL archive writer
│   │   └── dedup.py                # Echo prevention filter
│   ├── api/                        # HTTP API (FastAPI)
│   │   ├── server.py               # App factory + lifespan
│   │   ├── schemas.py              # Request/response Pydantic models
│   │   └── routes/
│   │       ├── memories.py         # CRUD + search endpoints
│   │       └── health.py           # Infrastructure health check
│   ├── mcp/                        # MCP server (Cursor integration)
│   │   └── server.py               # 4 tools over stdio transport
│   └── models/                     # Shared data models
│       ├── artifact.py             # MemoryArtifact (universal unit)
│       ├── conversation.py         # Conversation payload models
│       └── memory.py               # Search result models
└── tests/
    ├── test_engines.py             # Unit tests (no infra needed)
    └── test_integration.py         # E2E tests (requires running infra)
```

See the READMEs in each subdirectory for detailed documentation:
- [`src/forgetmenot/engines/`](src/forgetmenot/engines/) -- Source engine plugin system
- [`src/forgetmenot/core/`](src/forgetmenot/core/) -- Processing pipeline internals
- [`src/forgetmenot/api/`](src/forgetmenot/api/) -- HTTP API reference
- [`src/forgetmenot/mcp/`](src/forgetmenot/mcp/) -- MCP server and tool reference

## Running Tests

```bash
# Unit tests (no infrastructure required)
pytest tests/test_engines.py -v

# Integration tests (requires Qdrant, PostgreSQL, Ollama running)
pytest tests/test_integration.py -v

# All tests
pytest -v
```

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.12+ | Mem0 native, richest AI/ML ecosystem |
| API | FastAPI | Async, auto-docs, Pydantic integration |
| Memory Engine | Mem0 | Battle-tested extraction pipeline (52K+ GitHub stars) |
| Vector Store | Qdrant | Best self-hosted performance, hybrid search, Apache 2.0 |
| Graph Store | Neo4j | Multi-hop reasoning, entity relationships, Mem0 native support |
| Archive DB | PostgreSQL | ACID, SQL queries, migration-friendly |
| Embeddings | Ollama (self-hosted) | Privacy, no API costs, model flexibility |
| MCP SDK | `mcp` (Anthropic) | Official Python SDK, stdio transport |

## Roadmap

**v0.1** (current): Conversation memory via HTTP API + MCP. Manual save/recall.

**v0.2**: Autonomous save/recall (Cursor rules + hooks for auto-export), `memory_status` polling tool for async saves, time-window dedup filter.

**v0.2+**: Codebase indexing engine (tree-sitter + per-language native parser overrides, Go for performance), CLI capture tool (Go), Chrome extension (TypeScript), work ticket engine (GUS/Jira).

**Final goal**: Autonomous agent system that takes work requests and executes them with historical + repo-aware context.
