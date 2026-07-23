import asyncio
from pprint import pprint
from fastmcp import Client

client = Client("http://localhost:8006/mcp")


async def call_tool():
    async with client:
        tool_list = await client.list_tools()
        for tool in tool_list:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Input Schema: {tool.inputSchema}")
            print(f"Output Schema: {tool.outputSchema}")
            print(f"Annotations: {tool.annotations}")
            print("--------------------------------\n")
        print("--------------------------------\n")
        try:
            result = await client.call_tool("list_tables")
            pprint(result)
            print("--------------------------------\n")
        except Exception as e:
            print(f"Error: {e}")
        # result = await client.call_tool("list_table_columns", {"table": "users"})
        # print("--------------------------------\n")
        # pprint(result)
        # result = await client.call_tool("get_table_data", {"table": "users"})
        # print("--------------------------------\n")
        # pprint(result)
        # result = await client.call_tool(
        #     "query_table", {"table": "users", "query": "SELECT * FROM users"}
        # )
        # print("--------------------------------\n")
        # pprint(result)
        # result = await client.call_tool("get_table_schema", {"table": "users"})
        # print("--------------------------------\n")
        # pprint(result)


def main() -> None:
    asyncio.run(call_tool())


if __name__ == "__main__":
    main()
