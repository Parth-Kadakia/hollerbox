"""Bearer-token auth middleware.

Off by default — when `HOLLERBOX_API_KEY` is unset, every request is
allowed (matches the localhost-only assumption HollerBox started with).
When set, every API call must include either:

- `Authorization: Bearer <token>`  (preferred), or
- `?_token=<token>` query param   (for SSE / `<img src>` cases where
  custom headers are awkward in the browser).

Static SPA assets are intentionally public so the React app can load
and prompt the user for the token. The token's *use* (any /api/* or
/files/* call) is what's gated.

For the launcher / tunnel deployment story, the user sets the env var
once; the API logs it on startup so they can copy/paste it into the
browser's first-run prompt.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

ENV_VAR = "HOLLERBOX_API_KEY"

# Paths that DON'T require auth even when the env var is set. The SPA's
# HTML/JS/CSS, the manifest, the service worker, and any vite-prefixed
# bundle path. Everything else under /api/, /files/, /providers/, etc.
# is gated.
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/assets/",
    "/manifest",
    "/logo",
    "/favicon",
    "/sw.js",
    "/registerSW.js",
    "/workbox-",
    "/docs",        # OpenAPI docs page is unauthenticated — easier
    "/redoc",       # to inspect. /openapi.json IS protected when auth
                    # is on, so the docs UI won't actually load schemas
                    # without the token. Trade-off: kept simple.
)


def get_token_from_request(request: Request) -> str | None:
    """Return the token from header OR `?_token=` query, whichever is set."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    qp = request.query_params.get("_token")
    return qp.strip() if qp else None


def _path_is_public(path: str) -> bool:
    if path == "/" or path == "/index.html":
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        # Always allow CORS preflights — browsers can't send Authorization on those.
        if request.method == "OPTIONS":
            return await call_next(request)
        if _path_is_public(request.url.path):
            return await call_next(request)
        supplied = get_token_from_request(request)
        if supplied != self._token:
            return JSONResponse(
                status_code=401,
                content={"detail": "authentication required"},
                headers={"WWW-Authenticate": 'Bearer realm="hollerbox"'},
            )
        return await call_next(request)


def configure_auth(app: FastAPI) -> str | None:
    """Mount the middleware if a token is configured. Returns the token (or None)."""
    token = os.environ.get(ENV_VAR, "").strip() or None
    if token:
        app.add_middleware(BearerTokenMiddleware, token=token)
    return token
