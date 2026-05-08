import json
import os

import asyncpg
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "missing"))

SCHEMA_DESCRIPTION = """
Tables:
products(id integer primary key, name text, category text, price numeric, inventory_count integer)
orders(id integer primary key, product_id integer references products(id), customer_id integer, quantity integer, ordered_at timestamp)
"""


def _asyncpg_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/agentdb",
    ).replace("postgresql+asyncpg://", "postgresql://")


async def _query_to_sql(natural_language_query: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=(
            "Convert natural language to a single read-only PostgreSQL SELECT query. "
            "Only use the provided schema. Return JSON: {\"sql\": \"SELECT ...\"}."
        ),
        messages=[{
            "role": "user",
            "content": f"Schema:\n{SCHEMA_DESCRIPTION}\nQuestion: {natural_language_query}",
        }],
    )
    try:
        return json.loads(response.content[0].text)["sql"]
    except Exception:
        return response.content[0].text.strip()


async def run_data_lookup(natural_language_query: str):
    if not isinstance(natural_language_query, str) or not natural_language_query.strip():
        return {"error": "invalid_input", "code": "TOOL_MALFORMED"}

    try:
        sql = (await _query_to_sql(natural_language_query)).strip().rstrip(";")
        if not sql.lower().startswith("select"):
            return {"error": "sql_error", "code": "TOOL_SQL_ERROR", "detail": "Only SELECT statements are allowed"}

        conn = await asyncpg.connect(_asyncpg_url())
        try:
            rows = await conn.fetch(sql)
        finally:
            await conn.close()
        result = [dict(row) for row in rows]
        if not result:
            return {"error": "no_results", "code": "TOOL_EMPTY"}
        return result
    except Exception as exc:
        return {"error": "sql_error", "code": "TOOL_SQL_ERROR", "detail": str(exc)}
