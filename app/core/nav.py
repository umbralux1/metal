"""Разделы для меню в шапке и подвале. Кэшируются на минуту, чтобы не ходить в БД на каждый запрос."""

import time

from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send

from app.catalog.models import Category
from app.core.db import SessionLocal

TTL_SECONDS = 60
_cache: dict = {"at": 0.0, "items": []}


async def nav_categories() -> list[dict]:
    if _cache["items"] and time.monotonic() - _cache["at"] < TTL_SECONDS:
        return _cache["items"]
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Category.name, Category.slug, Category.path)
            .where(Category.parent_id.is_(None), Category.is_active.is_(True))
            .order_by(Category.sort, Category.name)
        )
    items = [{"name": name, "slug": slug, "url": f"/catalog/{path}/"} for name, slug, path in rows]
    _cache.update(at=time.monotonic(), items=items)
    return items


def reset_nav_cache() -> None:
    _cache.update(at=0.0, items=[])


class NavMiddleware:
    """Кладёт разделы в request.state.nav для HTML-страниц."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(("/static/", "/api/", "/health", "/admin")):
            scope.setdefault("state", {})["nav"] = await nav_categories()
        await self.app(scope, receive, send)
