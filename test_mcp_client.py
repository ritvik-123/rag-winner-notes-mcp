import asyncio
import os

import httpx2
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

load_dotenv()

URL = "https://rag-notes-mcp-585012498530.us-central1.run.app/mcp"
API_KEY = os.environ["MCP_API_KEY"]


async def main():
    # Generous timeout: a cold-started Cloud Run instance has no local
    # Hugging Face cache yet, so the first request after any idle period
    # can genuinely take a while. The default (5s) is fine for an already
    # warm instance but too tight for a cold start.
    http_client = httpx2.AsyncClient(headers={"x-api-key": API_KEY}, timeout=60.0)
    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            try:
                await session.initialize()
            except MCPError as e:
                print(f"code={e.code!r} message={e.message!r} data={e.data!r}")
                return
            result = await session.call_tool(
                "ask_notes", {"question": "What does Ritvik do?"}
            )
            print(result)


asyncio.run(main())
