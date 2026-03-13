import asyncio
import os
import sys
from pathlib import Path
from typing import Any


def _require_mcp() -> tuple[Any, Any, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Examples require the 'mcp' package. Install project dependencies first."
        ) from exc
    return ClientSession, stdio_client, StdioServerParameters


def build_server(default_scope: str) -> Any:
    _client_session, _stdio_client, stdio_server_parameters = _require_mcp()
    return stdio_server_parameters(
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
    client_session, stdio_client, _stdio_server_parameters = _require_mcp()
    async with stdio_client(build_server("engineering-standards")) as (r, w):
        async with client_session(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])


async def search_context_example() -> None:
    client_session, stdio_client, _stdio_server_parameters = _require_mcp()
    async with stdio_client(build_server("billing-domain")) as (r, w):
        async with client_session(r, w) as session:
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
    client_session, stdio_client, _stdio_server_parameters = _require_mcp()
    async with stdio_client(build_server("customer-escalation-acme")) as (r, w):
        async with client_session(r, w) as session:
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


async def run_examples() -> None:
    await list_tools_example()
    await search_context_example()
    await store_list_delete_example()


def main() -> None:
    asyncio.run(run_examples())


if __name__ == "__main__":
    main()
