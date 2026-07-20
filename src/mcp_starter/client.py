import asyncio
from fastmcp import Client

client = Client("http://localhost:8005/mcp")


async def call_tool(name: str):
    async with client:
        tool_list = await client.list_tools()
        print(tool_list)
        result = await client.call_tool("greet", {"name": name})
        print(result)


def main() -> None:
    asyncio.run(call_tool("Ford"))


if __name__ == "__main__":
    main()
