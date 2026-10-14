"""Одна каноническая форма URL: нижний регистр, слеш в конце, без двойных слешей → 301."""

import re

from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SKIP_PREFIXES = ("/static/", "/docs", "/redoc", "/openapi.json", "/health")


def canonical_path(path: str) -> str | None:
    """Возвращает исправленный путь или None, если путь уже канонический."""
    if path.startswith(SKIP_PREFIXES):
        return None
    fixed = re.sub(r"/{2,}", "/", path).lower()
    last_segment = fixed.rsplit("/", 1)[-1]
    if not fixed.endswith("/") and "." not in last_segment:
        fixed += "/"
    return fixed if fixed != path else None


class CanonicalUrlMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD"):
            target = canonical_path(scope["path"])
            if target is not None:
                query = scope.get("query_string", b"").decode("latin-1")
                response = RedirectResponse(target + (f"?{query}" if query else ""), status_code=301)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class NoIndexMiddleware:
    """Добавляет X-Robots-Tag: noindex ко всем ответам, когда ALLOW_INDEXING=false."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-robots-tag"]
                headers.append((b"x-robots-tag", b"noindex, nofollow"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)


class HeadAsGetMiddleware:
    """HEAD отвечает как GET, но без тела. Им пользуются Render, мониторинги и иногда поисковые роботы."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        async def send_without_body(message):
            if message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, send_without_body)
