# MCP Server

Model Context Protocol server for Cursor IDE integration. Exposes forgetmenot's memory operations as MCP tools over stdio transport.

## Setup

Add to your Cursor MCP configuration (Settings > MCP Servers, or edit the JSON config directly):

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

The server uses stdio transport -- Cursor launches it as a subprocess and communicates via stdin/stdout.

## Startup Behavior

On first tool invocation, the server lazily initializes all components:

1. Loads settings from environment / `.env`
2. Discovers and registers source engines
3. Initializes `MemoryEngine` (Mem0 wrapper with Qdrant + optional Neo4j)
4. Initializes `ArchiveStore` (PostgreSQL)
5. Initializes `DedupFilter`
6. **Pre-warms Ollama**: sends a lightweight embed request to load the embedding and LLM models into GPU/CPU memory, reducing latency on the first real operation

## Tools

### `memory_save`

Save a conversation to persistent memory. Archives raw data to PostgreSQL, then extracts facts via Mem0 into Qdrant (and Neo4j if enabled).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `conversation` | string | yes | -- | JSON array of `[{"role": "...", "content": "..."}]` messages, or plain text |
| `source` | string | no | `"cursor"` | Origin identifier |
| `session_id` | string | no | auto-generated UUID | Unique session identifier |
| `project` | string | no | `""` | Project name for metadata |
| `workspace` | string | no | `""` | Workspace path for metadata |
| `domain_tags` | string | no | `""` | Comma-separated tags (e.g. `"python,rag,architecture"`) |

**Input handling**: If `conversation` is valid JSON (an array of message objects), it's parsed as structured messages. Otherwise, it's treated as plain text and wrapped as a single user message.

**Progress reporting**: Reports progress to the MCP client at 0%, 10% (after archive), 20% (starting Mem0), and incrementally up to 90% (during Mem0 extraction), then 100%.

**Response** (JSON string):

```json
{
  "status": "saved",
  "session_id": "generated-uuid",
  "artifacts_count": 2,
  "mem0_results": [
    {
      "results": [
        {"id": "abc", "memory": "Extracted fact...", "event": "ADD"}
      ],
      "relations": {
        "added_entities": [
          [{"source": "forgetmenot", "relationship": "uses", "target": "qdrant"}]
        ]
      }
    }
  ]
}
```

On connection failure (Ollama unreachable), returns `{"status": "error", "message": "..."}` instead of crashing.

### `memory_recall`

Search memories by natural language query with dedup filtering.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | -- | Natural language search query |
| `user_id` | string | no | `"default"` | User ID to search |
| `limit` | int | no | `10` | Maximum results |
| `exclude_session_id` | string | no | `""` | Session ID to exclude from results (echo prevention) |

**Response** (JSON string):

```json
{
  "query": "database architecture decisions",
  "total": 3,
  "results": [
    {
      "id": "abc123",
      "memory": "Chose Qdrant for vector storage due to performance",
      "score": 0.89,
      "metadata": {"project": "forgetmenot", "session_id": "..."},
      "created_at": "2026-04-09T10:00:00Z",
      "updated_at": null
    }
  ]
}
```

### `memory_list_sessions`

List recent memory sessions with metadata.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | int | no | `20` | Maximum sessions to return |

**Response** (JSON string):

```json
{
  "sessions": [
    {
      "session_id": "abc-123",
      "source": "cursor",
      "message_count": 5,
      "project": "forgetmenot",
      "created_at": "2026-04-09T10:00:00Z"
    }
  ],
  "total": 1
}
```

### `memory_delete`

Delete a specific memory from Mem0 by its ID. Use `memory_recall` first to find the ID.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `memory_id` | string | yes | -- | ID of the memory to delete |

**Response** (JSON string):

```json
{"status": "deleted", "memory_id": "abc123", "result": {...}}
```

## Usage with Cursor Skills

The MCP server is designed to work with Cursor skills for structured save/recall workflows. See the `save-to-memory` skill (`.cursor/skills/save-to-memory/SKILL.md`) for the recommended pattern: summarize the conversation, infer metadata, call `memory_save`, confirm to the user.

## Notes

- All Mem0 operations (`add`, `search`) run in `asyncio.to_thread()` since Mem0 is synchronous. This keeps the MCP server's event loop responsive.
- The server is synchronous in terms of user experience -- `memory_save` blocks until Mem0 extraction completes and returns the full results. This is a deliberate v0.1 choice for visibility; async save with a `memory_status` polling tool is planned for v0.2.
