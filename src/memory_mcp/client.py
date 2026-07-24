import asyncio
from pprint import pprint
from fastmcp import Client

client = Client("http://localhost:8007/mcp")


async def call_tool():
    async with client:
        tool_list = await client.list_tools()
        for tool in tool_list:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            # pprint(f"Output Schema: {tool.outputSchema}")
            # pprint(f"input_schema: {tool.inputSchema}")
            print("--------------------------------\n")
        resource_list = await client.list_resources()
        for resource in resource_list:
            print(f"Resource: {resource.uri}")
            print(f"Description: {resource.description}")
            # print(f"URI: {resource.uri}")
            # print(f"MIME Type: {resource.mimeType}")
            print("--------------------------------\n")
        resource_list = await client.list_resource_templates()
        for resource in resource_list:
            print(f"Resource Template: {resource.uriTemplate}")
            print(f"Description: {resource.description}")
            # print(f"URI: {resource.uri}")
            # print(f"MIME Type: {resource.mimeType}")
            print("--------------------------------\n")
        try:
            # Reading a static resource
            result = await client.call_tool(
                "read_resource", {"uri": "resource:///memories"}
            )
            pprint(result.data)

            # result = await client.read_resource("resource:///memories")
            # pprint(result)
            print("--------------------------------\n")
            # result = await client.read_resource("file:///memories/Personality.md")
            # pprint(result)
            # print("--------------------------------\n")

            # result = await client.call_tool(
            #     "get_memories",
            # )
            # pprint(result)
            # print("--------------------------------\n")
        except Exception as e:
            print(f"Error: {e}")


def main() -> None:
    asyncio.run(call_tool())


if __name__ == "__main__":
    main()
