import aiofiles
import os
from starlette.applications import Starlette
from starlette.routing import Mount
import uvicorn

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.transforms import ResourcesAsTools

from starlette.responses import PlainTextResponse
from starlette.requests import Request

from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from cryptography.fernet import Fernet


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Set it in the process environment (e.g. K8s secrets, "
            "docker run -e, or locally: uv run --env-file .env memory-mcp)."
        )
    return value


MEMORY_ROOT = Path(__file__).parent / "memories"
MEMORY_ROOT.mkdir(parents=True, exist_ok=True)

# Configure token verification for your provider
# See the Token Verification guide for provider-specific setups
# token_verifier = JWTVerifier(
#     # jwks_uri="https://livemigrate.hub.loginradius.com/service/oidc/memory-mcp/.well-known/jwks.json",
#     jwks_uri="https://livemigrate.hub.loginradius.com/service/oidc/memory-mcp/jwks",
#     issuer="https://livemigrate.hub.loginradius.com/service/oidc/memory-mcp",
#     audience="1\",
#     required_scopes=["openid"],
# )

# Create the OAuth proxy
# auth = OAuthProxy(
#     # Provider's OAuth endpoints (from their documentation)
#     upstream_authorization_endpoint="https://livemigrate.hub.loginradius.com/service/oidc/memory-mcp/authorize",
#     upstream_token_endpoint="https://livemigrate.hub.loginradius.com/api/oidc/memory-mcp/token",
#     # Your registered app credentials
#     upstream_client_id="1\",
#     upstream_client_secret="",
#     # Token validation (see Token Verification guide)
#     token_verifier=token_verifier,
#     # Your FastMCP server's public URL
#     base_url="http://127.0.0.1:8007",
#     # LoginRadius rejects RFC 8707 `resource` (MCP URL). Keep resource
#     # binding on the FastMCP side only; do not forward it upstream.
#     forward_resource=False,
#     # LoginRadius requires a scope on authorize.
#     valid_scopes=["openid", "profile", "email"],
#     # Optional: customize the callback path (default is "/auth/callback")
#     # redirect_path="/custom/callback",
# )

_oauth_client_id = _require_env("OAUTH_CLIENT_ID")
_oauth_client_secret = _require_env("OAUTH_CLIENT_SECRET")
_jwt_signing_key = _require_env("JWT_SIGNING_KEY")
_storage_encryption_key = _require_env("STORAGE_ENCRYPTION_KEY")

MCP_PATH = os.environ.get("MCP_PATH", "")
MOUNT_PREFIX = os.environ.get("MCP_MOUNT_PREFIX", "")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8007")
_mcp_base_url = f"{BASE_URL}{MOUNT_PREFIX}"

cache_store = RedisStore(
    url=os.environ.get("REDIS_URL"),
)
auth = GoogleProvider(
    client_id=_oauth_client_id,
    client_secret=_oauth_client_secret,
    client_storage=FernetEncryptionWrapper(
        fernet=Fernet(_storage_encryption_key),
        key_value=cache_store,
    ),
    jwt_signing_key=_jwt_signing_key,
    base_url=_mcp_base_url,
)

mcp = FastMCP(
    "Memory MCP Server",
    instructions=(
        "Use this server to manage and query memories. "
        "Start with list_memories to see what memories are available, "
        "then use get_memory to retrieve a specific memory, "
        "and create_memory to add new memories. "
        "Use delete_memory to remove memories when they are no longer needed. "
        "Remember to always provide clear and concise instructions for memory management. "
    ),
    auth=auth,
    version="1.0.0",
)


# health check
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.tool(
    name="update_memory",
    description="Update a memory file",
    output_schema={
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
        },
    },
    annotations={"writeOnlyHint": True},
)
async def update_memory(memory_name: str, content: str) -> dict:
    try:
        async with aiofiles.open(MEMORY_ROOT / f"{memory_name}.md", "w") as f:
            await f.write(content)
        return {"success": True}
    except FileNotFoundError:
        raise ResourceError(f"Memory {memory_name} not found")


@mcp.tool(
    name="create_memory",
    description="Create a new memory file",
    output_schema={
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
        },
    },
    annotations={"writeOnlyHint": True},
)
async def create_memory(memory_name: str, content: str) -> dict:
    try:
        async with aiofiles.open(MEMORY_ROOT / f"{memory_name}.md", "w") as f:
            await f.write(content)
        return {"success": True}
    except FileNotFoundError:
        raise ResourceError(f"Memory {memory_name} not found")


@mcp.tool(
    name="delete_memory",
    description="Delete a memory file",
    output_schema={
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
        },
    },
    annotations={"writeOnlyHint": True},
)
async def delete_memory(memory_name: str) -> dict:
    try:
        (MEMORY_ROOT / f"{memory_name}.md").unlink()
        return {"success": True}
    except FileNotFoundError:
        raise ResourceError(f"Memory {memory_name} not found")


@mcp.tool(
    name="get_memory",
    description="Get a memory file",
    output_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
    },
    annotations={"readOnlyHint": True},
)
async def get_memory(memory_name: str) -> dict:
    try:
        async with aiofiles.open(MEMORY_ROOT / f"{memory_name}.md", "r") as f:
            return {"content": await f.read()}
    except FileNotFoundError:
        raise ResourceError(f"Memory {memory_name} not found")


@mcp.tool(
    name="get_memories",
    description="List all memory files",
    output_schema={
        "type": "object",
        "properties": {
            "memories": {"type": "array", "items": {"type": "string"}},
        },
    },
    annotations={"readOnlyHint": True},
)
async def get_memories() -> dict:
    memories = []
    for file in MEMORY_ROOT.glob("*.md"):
        memories.append(file.stem)
    return {"memories": memories}


@mcp.resource(
    uri="resource:///memories",
    name="memories",
    description="A collection of memories",
    mime_type="application/json",
)
async def list_memories() -> dict:
    memories = []
    for file in MEMORY_ROOT.glob("*.md"):
        memories.append(file.stem)
    return {"memories": memories}


@mcp.resource(
    uri="resource:///memories/{memory_name}",
    name="memory_resource",
    description="A memory resource",
    mime_type="text/markdown",
)
async def read_memory(memory_name: str) -> str:
    try:
        async with aiofiles.open(MEMORY_ROOT / f"{memory_name}.md", "r") as f:
            return await f.read()
    except FileNotFoundError:
        raise ResourceError(f"Memory {memory_name} not found")


mcp.add_transform(ResourcesAsTools(mcp))


mcp_app = mcp.http_app(path=MCP_PATH, stateless_http=True)

well_known_routes = auth.get_well_known_routes(mcp_path=MCP_PATH)

app = Starlette(
    routes=[*well_known_routes, Mount(path=MOUNT_PREFIX, app=mcp_app)],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)
