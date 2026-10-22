from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import FilterLanding
from app.core.config import settings
from app.core.db import get_session
from app.core.maps import yandex_map
from app.core.templating import templates
from app.delivery.service import list_active_vehicles
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
            "landings": list(landings),
            "jsonld": [jsonld.to_script(jsonld.organization())],
        },
    )


@router.get("/contacts/", response_class=HTMLResponse, name="contacts")
async def contacts(request: Request):
    meta = PageMeta(
        title=f"Контакты и адрес склада металлопроката в {city_prep()} | {settings.site_name}",
        description=f"Адрес склада, схема проезда на карте, телефон и часы работы. {settings.work_hours}. "
        f"☎ {settings.phone}",
        h1="Контакты",
        canonical=absolute("/contacts/"),
        robots=robots_for(request),
    )
    crumbs = [("Главная", "/"), ("Контакты", "/contacts/")]
    return templates.TemplateResponse(
        request,
        "contacts.html",
        {
            "meta": meta,
            "map": yandex_map(),
            "breadcrumbs": crumbs,
            "jsonld": [jsonld.to_script(jsonld.local_business()), jsonld.to_script(jsonld.breadcrumbs(crumbs))],
        },
    )


@router.get("/delivery/", response_class=HTMLResponse, name="delivery")
async def delivery(request: Request, session: AsyncSession = Depends(get_session)):
    meta = PageMeta(
        title=f"Доставка металлопроката по {settings.city_prepositional} и области: тарифы | {settings.site_name}",
        description=f"Доставка металла грузовиком, манипулятором и длинномером. Цены по машинам, "
        f"расчёт по километрам. ☎ {settings.phone}",
        h1="Доставка металлопроката",
        canonical=absolute("/delivery/"),
        robots=robots_for(request),
    )
    crumbs = [("Главная", "/"), ("Доставка", "/delivery/")]
    return templates.TemplateResponse(
        request,
        "delivery.html",
        {
            "meta": meta,
            "vehicles": await list_active_vehicles(session),
            "max_km": settings.delivery_max_km,
            "breadcrumbs": crumbs,
            "jsonld": [jsonld.to_script(jsonld.breadcrumbs(crumbs))],
        },
    )


@router.get("/health", include_in_schema=False)
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("select 1"))
    return {"status": "ok"}
