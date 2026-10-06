from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from user_store import resolve_api_key


class ApiKeyMiddleware:
    """Raw ASGI middleware: rejects any HTTP request whose API key doesn't
    resolve to a known user.

    Wraps the app directly (instead of Starlette's BaseHTTPMiddleware) so it
    never buffers the streaming responses the MCP Streamable HTTP transport
    relies on -- it just inspects the request and either forwards it
    untouched or short-circuits with a 401. Only checks that the key is
    valid here; the tool itself re-resolves it to a user_id (see
    mcp_server.py) rather than this layer trying to pass that along.
    """

    def __init__(self, app: ASGIApp, header_name: str = "x-api-key"):
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Non-HTTP scopes (lifespan startup/shutdown, websockets) pass through untouched.
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        provided_key = request.headers.get(self.header_name)

        if provided_key is None or resolve_api_key(provided_key) is None:
            response = JSONResponse({"error": "invalid or missing API key"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
