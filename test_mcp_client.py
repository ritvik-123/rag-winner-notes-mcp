import asyncio
import os

import httpx2
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

load_dotenv()

URL = "http://127.0.0.1:8000/mcp"
API_KEY = os.environ["MCP_API_KEY"]


async def main():
    http_client = httpx2.AsyncClient(headers={"x-api-key": API_KEY})
    async with streamable_http_client(URL, http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "ask_notes", {"question": "What does Ritvik do?"}
            )
            print(result)


asyncio.run(main())
