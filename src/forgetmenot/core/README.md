# Core Processing Pipeline

The `core/` package contains the shared infrastructure that all source engines feed into: the Mem0 wrapper, raw archive persistence, echo prevention, and engine discovery.

## Components

### MemoryEngine (`memory_engine.py`)

Wraps [Mem0](https://github.com/mem0ai/mem0) `Memory` with forgetmenot-specific configuration and connection resilience.

**Configuration** (`build_mem0_config`):
- **Vector store**: Qdrant with configurable host/port and collection name `"forgetmenot"`
- **LLM**: Ollama by default (model set via `FORGETMENOT_MEM0_LLM_MODEL`), used for fact extraction
- **Embedder**: Ollama embedding model (set via `FORGETMENOT_EMBEDDING_MODEL`)
- **Graph store**: Neo4j (optional, disabled by default due to ~25s add / ~5.5s search overhead)
- **Custom prompt**: Instructs Mem0 to focus on preferences, decisions, entities, and explicit "remember" requests while ignoring transient debug output and filler

**Retry logic**: All Mem0 calls are wrapped in `_retry_on_connection_error` which retries 3 times with exponential backoff (2s, 4s, 8s) on connection failures. Catches `ConnectionError`, `OSError`, and any exception with "Connection" in its class name (covers Ollama-specific error types).

**Methods**:

| Method | Description |
|--------|-------------|
| `add(messages, user_id, metadata)` | Send messages through Mem0's extraction pipeline. Returns extracted facts, entities, and graph relationships. |
| `search(query, user_id, limit, filters)` | Semantic search over extracted memories. |
| `get(memory_id)` | Retrieve a specific memory by ID. |
| `get_all(user_id)` | Retrieve all memories for a user. |
| `delete(memory_id)` | Delete a specific memory. |
| `delete_all(user_id)` | Delete all memories for a user. |

### ArchiveStore (`archive.py`)

Async PostgreSQL persistence layer for raw, unprocessed source data. Uses SQLAlchemy async with `asyncpg`.

**Design**: Accepts any SQLAlchemy model that inherits from `ArchiveBase` (defined in `engines/base.py`). Each engine defines its own archive table schema, and the store writes them polymorphically. This means adding a new engine with a new table shape requires zero changes to `ArchiveStore`.

**Methods**:

| Method | Description |
|--------|-------------|
| `init_tables()` | Create all `ArchiveBase`-derived tables (idempotent DDL). |
| `save(record)` | Persist a single archive record with auto-commit/rollback. |
| `save_many(records)` | Persist multiple records in one transaction. |
| `query_by_session(model, session_id)` | Retrieve all archive records for a session. |
| `close()` | Dispose the async engine connection pool. |

### DedupFilter (`dedup.py`)

Post-retrieval echo prevention filter. Applied to Mem0 search results before returning them to the caller.

**Two-layer filtering**:

1. **Session exclusion**: If `exclude_session_id` is provided, any result whose metadata contains a matching `session_id` is dropped. This prevents the model from retrieving what it just saved in the current session.

2. **Near-duplicate detection**: For results above the similarity score threshold, a token-overlap check (Jaccard-style) compares each result against previously accepted results in the same response. Duplicates above the threshold (default 0.95) are dropped. This catches cases where Mem0 returns near-identical memories phrased slightly differently.

Note: Mem0 also performs its own dedup during `add()` -- it compares new facts against existing ones and decides whether to add, update, or skip. The `DedupFilter` is an additional safety layer on the retrieval side.

### EngineRegistry (`engine_registry.py`)

Auto-discovers and manages source engine plugins.

**Discovery**: At startup, scans `forgetmenot.engines` using `pkgutil.iter_modules`. For each module (excluding `base.py`), imports it and looks for `SourceEngine` subclasses with a string `engine_type`. Found engines are instantiated and registered.

**Usage**:
```python
registry = EngineRegistry()
registry.discover()

engine = registry.get("conversation")  # returns ConversationEngine instance
registry.list_engines()                # ["conversation"]
```

Raises `KeyError` with the list of available engines if an unknown type is requested.

## Data Flow

```
  1. Client sends raw data (HTTP POST or MCP tool call)
                │
  2. EngineRegistry routes to the right SourceEngine
                │
  3. Engine.normalize() → [MemoryArtifact, ...]
                │
         ┌──────┴──────┐
         ▼              ▼
  4a. ArchiveStore    4b. Engine.extract_for_mem0()
      .save()              │
      (PostgreSQL)         ▼
                     5. MemoryEngine.add()
                         (Mem0 → Qdrant + Neo4j)
                              │
  6. On retrieval:            │
     MemoryEngine.search()    │
           │                  │
           ▼                  │
     DedupFilter.filter()     │
           │                  │
           ▼                  │
     Filtered results         │
     returned to client       │
```
