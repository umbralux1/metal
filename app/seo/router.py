from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Category, FilterLanding, Product
from app.core.db import get_session
from app.seo.meta import absolute

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt() -> str:
    return "\n".join(
        [
            "User-agent: *",
            "Disallow: /cart/",
            "Disallow: /*?*sort=",
            "",
            "User-agent: Yandex",
            "Disallow: /cart/",
            "Clean-param: sort&order&utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid",
            "",
            f"Sitemap: {absolute('/sitemap.xml')}",
            "",
        ]
    )


def _url(loc: str, lastmod: datetime | None = None) -> str:
    mod = f"<lastmod>{lastmod.date().isoformat()}</lastmod>" if lastmod else ""
    return f"<url><loc>{escape(absolute(loc))}</loc>{mod}</url>"


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(session: AsyncSession = Depends(get_session)) -> Response:
    """Только индексируемые страницы. При росте каталога разбить на sitemap-index по типам."""
    urls = [_url("/"), _url("/catalog/")]
    for c in await session.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.path)):
        urls.append(_url(c.url, c.updated_at))
    landings = select(FilterLanding).where(FilterLanding.is_indexable.is_(True)).order_by(FilterLanding.path)
    for landing in await session.scalars(landings):
        urls.append(_url(landing.url, landing.updated_at))
    for p in await session.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.path)):
        urls.append(_url(p.url, p.updated_at))
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    )
    return Response(body, media_type="application/xml")
