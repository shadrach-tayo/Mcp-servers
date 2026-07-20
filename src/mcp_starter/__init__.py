from fastmcp import FastMCP

mcp = FastMCP("Todo MCP Server")


@mcp.tool
def greet(name: str) -> str:
    return f"Yellow, {name}"


def main() -> None:
    mcp.run(transport="http", host="127.0.0.1", port=8005)


if __name__ == "__main__":
    main()
