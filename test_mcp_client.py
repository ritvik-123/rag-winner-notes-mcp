import asyncio
import os

import httpx2
import requests
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from test_web_api_client import get_id_token

load_dotenv()

WEB_API_BASE_URL = os.environ.get("WEB_API_BASE_URL", "http://localhost:8080")
# mcp_server.py defaults to the same port (8080) as web_api.py, so when
# running both locally at once to mint-then-call, start mcp_server.py with
# PORT set to something else, e.g. `set PORT=8081 && python src\mcp_server.py`.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8081/mcp")


def mint_api_key() -> str:
    """Sign in and mint a personal MCP API key via the web API, exactly like
    test_web_api_client.py does -- MCP access is no longer the single shared
    MCP_API_KEY from the pre-phase-D version."""
    id_token = get_id_token()
    response = requests.post(
        f"{WEB_API_BASE_URL}/api-keys",
        headers={"Authorization": f"Bearer {id_token}"},
    )
    response.raise_for_status()
    return response.json()["api_key"]


async def main():
    api_key = mint_api_key()
    print(f"Minted MCP API key: {api_key}\n")

    # Generous timeout: against a cold-started Cloud Run instance (no local
    # Hugging Face cache yet), the first request after any idle period can
    # genuinely take a while. The default (5s) is fine for an already-warm
    # instance or a local run but too tight for a cold start.
    http_client = httpx2.AsyncClient(headers={"x-api-key": api_key}, timeout=60.0)
    async with streamable_http_client(MCP_SERVER_URL, http_client=http_client) as (read, write):
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
