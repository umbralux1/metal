from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.seo.meta import absolute

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt() -> str:
    if not settings.allow_indexing:
        return "User-agent: *\nDisallow: /\n"
    return "\n".join(
        [
            "User-agent: *",
            "Disallow: /cart/",
            "Disallow: /api/",
            "Disallow: /admin/",
            "Disallow: /*?*sort=",
            "",
            "User-agent: Yandex",
            "Disallow: /cart/",
            "Disallow: /api/",
            "Disallow: /admin/",
            "Clean-param: sort&order&utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid",
            "",
            f"Sitemap: {absolute('/sitemap.xml')}",
            "",
        ]
    )
