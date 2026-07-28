# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

# --- runtime ---
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app pyproject.toml uv.lock ./

USER app

# Which ASGI app to run (override per service), e.g. memory_mcp.server:app
ARG MCP_SERVER_SPEC=memory_mcp.server:app
ARG MCP_PORT=8007
ENV MCP_SERVER_SPEC=${MCP_SERVER_SPEC} \
    MCP_PORT=${MCP_PORT} \
    PYTHONPATH=/app/src

EXPOSE ${MCP_PORT}

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ[\"MCP_PORT\"]}/api/health', timeout=2)" \
  || exit 1

CMD ["sh", "-c", "uvicorn \"$MCP_SERVER_SPEC\" --host 0.0.0.0 --port \"$MCP_PORT\""]