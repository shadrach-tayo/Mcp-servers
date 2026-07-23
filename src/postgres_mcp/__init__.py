# import asyncio
from fastmcp import FastMCP

# from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from postgres_mcp.postgres_adapter import PostgresClient

mcp = FastMCP(
    "Postgres MCP Server",
    instructions=(
        "Use this server to explore and query a Postgres database. "
        "Start with list_tables to discover available tables, then use "
        "get_table_schema or list_table_columns before reading data. "
        "Use get_table_data for full table contents, or query_table with a "
        "table name and WHERE clause / filter expression for targeted reads. "
        "Prefer schema introspection before querying unfamiliar tables. "
        "Do not invent table or column names — only use what these tools return."
    ),
    version="1.0.0",
)


postgres_client = PostgresClient(
    host="localhost",
    port=5438,
    database="livemigrate",
    user="postgres",
    password="postgres",
)


@mcp.tool(
    app=True,
    tags={"public"},
    name="list_tables",
    description="List all tables in the database",
    output_schema={
        "type": "object",
        "properties": {
            "tables": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["tables"],
    },
    timeout=1.0,
    annotations=ToolAnnotations(
        title="List Tables", readOnlyHint=True, openWorldHint=True
    ),
)
async def list_tables() -> dict:
    """List all tables in the database"""

    # await asyncio.sleep(2.0)

    # raise ToolError("Failed to list tables")
    tables = postgres_client.fetch_tables()

    return {"tables": tables}


@mcp.tool(
    app=True,
    name="list_table_columns",
    description="List all columns in a table",
    output_schema={
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["columns"],
    },
)
def list_table_columns(table: str) -> dict:
    """List all columns in a table"""
    return {"columns": postgres_client.fetch_table_columns(table)}


@mcp.tool(
    app=True,
    name="get_table_data",
    description="Get all data from a table",
    output_schema={
        "type": "object",
        "properties": {
            "data": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["data"],
    },
    annotations={"readOnlyHint": True},
)
def get_table_data(table: str) -> dict:
    """Get all data from a table"""
    return {"data": postgres_client.fetch_table_data(table)}


@mcp.tool(
    app=True,
    name="query_table",
    description="Query a table with a WHERE clause / filter expression",
    output_schema={
        "type": "object",
        "properties": {
            "data": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["data"],
    },
)
def query_table(table: str, whereClause: str) -> dict:
    """Query a table with a WHERE clause / filter expression"""
    return {"data": postgres_client.query_table(table, whereClause)}


@mcp.tool(
    app=True,
    name="get_table_schema",
    description="Get the schema of a table",
    output_schema={
        "type": "object",
        "properties": {
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "column_name": {"type": "string"},
                        "data_type": {"type": "string"},
                    },
                },
            },
        },
        "required": ["data"],
    },
)
def get_table_schema(table: str) -> dict:
    """Get the schema of a table"""
    return {"data": postgres_client.fetch_table_schema(table)}


@mcp.custom_route("/health", methods=["GET"])
def health() -> str:
    """Check the health of the server"""
    return "OK"


# mcp.disable(tags={"public"})


def main() -> None:
    mcp.run(transport="http", host="127.0.0.1", port=8006)


if __name__ == "__main__":
    main()
