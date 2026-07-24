from pathlib import Path
import aiofiles
from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError
from fastmcp.server.transforms import ResourcesAsTools

MEMORY_ROOT = Path(__file__).parent / "memories"
MEMORY_ROOT.mkdir(parents=True, exist_ok=True)

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
    version="1.0.0",
)


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


def main() -> None:
    # Add the transform - creates list_resources and read_resource tools
    # Run the MCP
    mcp.run(transport="http", host="127.0.0.1", port=8007)


if __name__ == "__main__":
    main()
