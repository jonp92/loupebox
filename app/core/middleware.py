from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.origins import public_origins

PUBLIC_PATH = f"{settings.api_prefix}/feedback"


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """Two CORS policies:

    * POST {api_prefix}/feedback (public ingest): any origin registered on an active site; no credentials.
    * everything else (admin API): only `settings.admin_origins`; credentials allowed for the
      refresh cookie.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        if not origin:
            return await call_next(request)

        public = request.url.path == PUBLIC_PATH
        allowed = public_origins.contains(origin) if public else origin in settings.admin_origins

        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            if not allowed:
                return Response(status_code=403)
            return Response(status_code=204, headers=self._headers(origin, public, preflight=True))

        response = await call_next(request)
        if allowed:
            response.headers.update(self._headers(origin, public, preflight=False))
        response.headers.append("Vary", "Origin")
        return response

    @staticmethod
    def _headers(origin: str, public: bool, preflight: bool) -> dict[str, str]:
        headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        if not public:
            headers["Access-Control-Allow-Credentials"] = "true"
        if preflight:
            headers["Access-Control-Max-Age"] = "600"
            if public:
                headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
                headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
            else:
                headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        return headers


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects oversized request bodies, including chunked ones with no Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int, overrides: dict[str, int] | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.overrides = overrides or {}  # path suffix -> larger limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        max_bytes = next((v for k, v in self.overrides.items() if path.endswith(k)), self.max_bytes)
        too_large = JSONResponse({"detail": "Request body too large"}, status_code=413)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None:
            if not length.isdigit():
                await JSONResponse({"detail": "Bad Content-Length"}, status_code=400)(
                    scope, receive, send
                )
                return
            if int(length) > max_bytes:
                await too_large(scope, receive, send)
                return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await too_large(scope, receive, send)
