# Source Engines

The engine system is forgetmenot's extensibility layer. Each engine handles a specific data source -- conversations, codebases, web pages, work tickets -- and normalizes it into `MemoryArtifact` objects that flow through the shared processing pipeline.

## How It Works

```
  Raw Input (any format)
       │
       ▼
  ┌──────────────────┐
  │ EngineRegistry    │  auto-discovers engines at startup
  │   .get("type")    │  routes to the right engine
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────────────────────────────┐
  │ SourceEngine (ABC)                            │
  │                                               │
  │  normalize(raw_input)  → [MemoryArtifact]     │  parse + validate + normalize
  │  extract_for_mem0()    → [{messages}]         │  format for Mem0 extraction
  │  archive_schema()      → SQLAlchemy model     │  define raw archive table
  │  prepare_archive_record() → ORM instance      │  create archive row
  └───────────────────────────────────────────────┘
           │
           ▼
     MemoryArtifact objects flow to:
       → ArchiveStore (PostgreSQL, raw verbatim)
       → MemoryEngine (Mem0 → Qdrant + Neo4j)
```

## MemoryArtifact

The universal unit of knowledge. Every engine produces these:

```python
class MemoryArtifact(BaseModel):
    id: str              # Deterministic SHA-256 hash (auto-generated)
    engine_type: str     # "conversation", "codebase", "web", etc.
    source: str          # "cursor", "cli", "browser", "api", "repo"
    session_id: str      # Groups related artifacts together
    content: str         # The actual text/code/content
    content_type: str    # "dialogue", "function", "class", "webpage", etc.
    metadata: dict       # Engine-specific metadata
    timestamp: datetime  # When the artifact was created
    tags: list[str]      # Domain tags for filtering
```

The `id` is deterministically computed from `(engine_type, session_id, content)` so the same input always produces the same ID (useful for dedup and idempotency).

## SourceEngine ABC

To create a new engine, subclass `SourceEngine` and implement three methods:

```python
from forgetmenot.engines.base import ArchiveBase, SourceEngine
from forgetmenot.models.artifact import MemoryArtifact

class MyEngine(SourceEngine):
    engine_type = "my_type"  # must be a string class variable

    def normalize(self, raw_input: dict) -> list[MemoryArtifact]:
        # Parse raw_input, validate it, produce MemoryArtifact objects
        ...

    def extract_for_mem0(self, artifacts: list[MemoryArtifact]) -> list[dict]:
        # Format artifacts as Mem0-compatible message lists:
        # [{"messages": [{"role": "user", "content": "..."}], "user_id": "default"}]
        ...

    def archive_schema(self) -> type[ArchiveBase]:
        # Return a SQLAlchemy model class for raw archival
        ...
```

Place the file in `src/forgetmenot/engines/`. The `EngineRegistry` auto-discovers it at startup -- no registration code needed.

## ConversationEngine (v0.1)

The currently implemented engine. Handles multi-format conversation ingestion.

### Supported input formats

| Format | Description |
|--------|-------------|
| Standard message list | `[{"role": "user", "content": "..."}, ...]` (OpenAI/Anthropic compatible) |
| Cursor JSONL | Cursor agent transcripts with content blocks; use `normalize_cursor_jsonl()` helper |
| Raw text | Plain text wrapped as a single user message; use `normalize_raw_text()` helper |

### Processing flow

1. Validates input against `ConversationPayload` (Pydantic model)
2. Creates one `MemoryArtifact` per message with `content_type="dialogue"`
3. For Mem0 extraction: groups all artifacts by session into a single conversation so Mem0 sees the full dialogue context
4. Archive: stores the complete raw JSON payload in the `conversation_archives` table

### Archive schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | `Integer` (PK) | Auto-increment |
| `session_id` | `String(64)` | Session identifier (indexed) |
| `source` | `String(32)` | Origin: cursor, cli, browser, api |
| `raw_json` | `Text` | Complete raw input payload |
| `message_count` | `Integer` | Number of messages |
| `project` | `String(256)` | Project name (nullable) |
| `workspace` | `String(512)` | Workspace path (nullable) |
| `created_at` | `DateTime(tz)` | Ingestion timestamp |

## Engine Discovery

The `EngineRegistry` in `core/engine_registry.py` scans the `forgetmenot.engines` package at startup using `pkgutil.iter_modules`. It finds all classes that:

1. Subclass `SourceEngine`
2. Are not `SourceEngine` itself
3. Have a string `engine_type` class variable

Each discovered engine is instantiated and registered. The registry provides `get(engine_type)` to route requests to the right engine.

## Planned Engines

**CodebaseEngine** (v0.2+): AST-level code indexing using tree-sitter as the default parser with per-language native parser overrides for deeper analysis. Produces symbol-level artifacts (functions, classes, imports). Written in Go for performance, communicating with forgetmenot via the HTTP API.

**WebEngine** (future): Web page ingestion and indexing. Similar pattern to the existing `web-rag` project's scraping pipeline.

**WorkTicketEngine** (future): Ingests work tickets from Jira, GUS, or plain text instructions. Normalizes ticket fields (description, acceptance criteria, comments) into artifacts.
