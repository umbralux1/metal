from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import repository as repo
from app.catalog.models import FilterLanding
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import templates
from app.seo import jsonld
from app.seo.meta import PageMeta, absolute, city_prep, robots_for

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="home")
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    meta = PageMeta(
        title=f"Металлопрокат купить в {city_prep()} в розницу с доставкой | {settings.site_name}",
        description=f"Металлопрокат в розницу от 1 штуки: арматура, профильная труба, уголок, лист, профнастил. "
        f"Доставка по {city_prep()} и области, резка в размер. ☎ {settings.phone}",
        h1=f"Металлопрокат в {city_prep()} с доставкой",
        canonical=absolute("/"),
        robots=robots_for(request),
    )
    landings = await session.scalars(
        select(FilterLanding).where(FilterLanding.is_indexable.is_(True)).order_by(FilterLanding.sort).limit(12)
    )
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "meta": meta,
            "categories": await repo.top_categories(session),
            "landings": list(landings),
            "jsonld": [jsonld.to_script(jsonld.organization())],
        },
    )


@router.get("/health", include_in_schema=False)
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ok"}
