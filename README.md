# mcp-starter

Local FastMCP servers managed with **uv** (Python 3.13+).

## Setup

```bash
uv sync
source .venv/bin/activate  # optional; uv run works without it
```

## Servers

| Server | Entrypoint | HTTP port |
|---|---|---|
| Todo MCP | `mcp-starter` | `8005` |
| Postgres MCP | `postgres-mcp` | `8006` |

### Run (no reload)

```bash
uv run mcp-starter
uv run postgres-mcp
```

### Run with hot reload (recommended for development)

Prefer FastMCP’s built-in reload (cleaner process teardown than wrapping with `watchfiles`):

```bash
# Todo MCP
uv run fastmcp run src/mcp_starter/__init__.py:mcp \
  --transport http --host 127.0.0.1 --port 8005 \
  --reload --reload-dir src

# Postgres MCP
uv run fastmcp run src/postgres_mcp/__init__.py:mcp \
  --transport http --host 127.0.0.1 --port 8006 \
  --reload --reload-dir src
```

Alternative using `watchfiles`:

```bash
uv run watchfiles --filter python 'uv run postgres-mcp' src
```

If reload fails with `address already in use`, an old process is still bound to the port:

```bash
lsof -nP -iTCP:8006 -sTCP:LISTEN
kill <pid>
```

## Clients

```bash
uv run mcp-client        # hits http://localhost:8005/mcp
uv run postgres-client   # hits http://localhost:8006/mcp
```

Start the matching server first.

## Claude Desktop (stdio)

Claude Desktop uses **stdio**, not HTTP. Add to
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
"todo-mcp": {
  "command": "uv",
  "args": [
    "--directory",
    "/Users/tayo/code/courses/AI/Claude/mcp-starter",
    "run",
    "fastmcp",
    "run",
    "src/mcp_starter/__init__.py:mcp"
  ]
},
"postgres-mcp": {
  "command": "uv",
  "args": [
    "--directory",
    "/Users/tayo/code/courses/AI/Claude/mcp-starter",
    "run",
    "fastmcp",
    "run",
    "src/postgres_mcp/__init__.py:mcp"
  ]
}
```

Fully quit and reopen Claude Desktop after editing.

## Package commands

```bash
uv add <package>
uv remove <package>
uv sync
```
