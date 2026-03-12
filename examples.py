import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


def build_server(default_scope: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
        env={
            **os.environ,
            "PROJECT_ID": default_scope,
            "PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS": "300",
            "PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS": "900",
        },
    )


async def list_tools_example() -> None:
    async with stdio_client(build_server("engineering-standards")) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])


async def search_context_example() -> None:
    async with stdio_client(build_server("billing-domain")) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_context",
                {
                    "query": "billing retry policy and ledger reconciliation constraints",
                    "repo": "billing-api",
                    "limit": 4,
                },
            )
            print(result.content[0].text if result.content else "no content")


async def store_list_delete_example() -> None:
    async with stdio_client(build_server("customer-escalation-acme")) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            store = await session.call_tool(
                "store_memory",
                {
                    "project_id": "customer-escalation-acme",
                    "content": "Documented escalation handoff and invoice replay guardrails.",
                    "repo": "support-playbooks",
                    "category": "summary",
                    "source_kind": "summary",
                    "upsert_key": "acme-escalation-handoff",
                },
            )
            print("STORE:", store.content[0].text)
            listed = await session.call_tool(
                "list_memories",
                {
                    "project_id": "customer-escalation-acme",
                    "repo": "support-playbooks",
                    "limit": 5,
                },
            )
            print("LIST:", listed.content[0].text.splitlines()[0])
            deleted = await session.call_tool(
                "delete_memory",
                {
                    "project_id": "customer-escalation-acme",
                    "upsert_key": "acme-escalation-handoff",
                },
            )
            print("DELETE:", deleted.content[0].text)


asyncio.run(list_tools_example())
asyncio.run(search_context_example())
asyncio.run(store_list_delete_example())
