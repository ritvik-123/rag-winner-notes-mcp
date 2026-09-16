from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ApiKeyMiddleware:
    """Raw ASGI middleware: rejects any HTTP request missing the correct API key.

    Wraps the app directly (instead of Starlette's BaseHTTPMiddleware) so it
    never buffers the streaming responses the MCP Streamable HTTP transport
    relies on -- it just inspects the request and either forwards it
    untouched or short-circuits with a 401.
    """

    def __init__(self, app: ASGIApp, api_key: str, header_name: str = "x-api-key"):
        self.app = app
        self.api_key = api_key
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Non-HTTP scopes (lifespan startup/shutdown, websockets) pass through untouched.
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        provided_key = request.headers.get(self.header_name)

        if provided_key != self.api_key:
            response = JSONResponse({"error": "invalid or missing API key"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
