import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/memories/.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m",
            "debugpy",
            "--listen",
            "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/memories/mcp_server.py",
        ],
        env={
            **os.environ,
            "PROJECT_ID": "customcheckout-practices",
            "PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS": "300",
            "PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS": "900",
        },
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print([t.name for t in tools.tools])

asyncio.run(main())


import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/memories.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m",
            "debugpy",
            "--listen",
            "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/memories/memory/mcp_server.py",
        ],
        env={
            **os.environ,
            "PROJECT_ID": "customcheckout-practices",
            "PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS": "300",
            "PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS": "900",
        },
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(
                "search_context",
                {
                    "query": "automatic discounts constraints in customcheckout",
                    "repo": "customcheckout",
                    "limit": 4,
                },
            )
            print(res.content[0].text if res.content else "no content")

asyncio.run(main())


import asyncio, os
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main():
    server = StdioServerParameters(
        command="/Users/willjayroe/Desktop/repos/memories.env/bin/python",
        args=[
            "-Xfrozen_modules=off",
            "-m",
            "debugpy",
            "--listen",
            "5678",
            "--wait-for-client",
            "/Users/willjayroe/Desktop/repos/memories/memory/mcp_server.py",
        ],
        env={
            **os.environ,
            "PROJECT_ID": "customcheckout-practices",
            "PROJECT_MEMORY_PROJECT_SEARCH_TIMEOUT_SECONDS": "300",
            "PROJECT_MEMORY_GLOBAL_SEARCH_TIMEOUT_SECONDS": "900",
        },
    )
    async with stdio_client(server) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            store = await s.call_tool(
                "store_memory",
                {
                    "project_id": "customcheckout-practices",
                    "content": "debug roundtrip memory",
                    "repo": "customcheckout",
                    "category": "summary",
                    "source_kind": "summary",
                    "upsert_key": "debug-roundtrip",
                },
            )
            print("STORE:", store.content[0].text)
            listed = await s.call_tool(
                "list_memories",
                {
                    "project_id": "customcheckout-practices",
                    "repo": "customcheckout",
                    "limit": 5,
                },
            )
            print("LIST:", listed.content[0].text.splitlines()[0])
            deleted = await s.call_tool(
                "delete_memory",
                {
                    "project_id": "customcheckout-practices",
                    "upsert_key": "debug-roundtrip",
                },
            )
            print("DELETE:", deleted.content[0].text)

asyncio.run(main())