from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import repository as repo
from app.catalog.models import Category, FilterLanding, Product
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import templates
from app.seo import jsonld
from app.seo.meta import PageMeta, absolute, category_meta, city_prep, landing_meta, product_meta, robots_for

router = APIRouter()

CATALOG_ROOT = ("Каталог", "/catalog/")


def _crumbs(categories: list[Category], tail: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    items = [("Главная", "/"), CATALOG_ROOT] + [(c.name, c.url) for c in categories]
    return items + ([tail] if tail else [])


@router.get("/catalog/", response_class=HTMLResponse, name="catalog_index")
async def catalog_index(request: Request, session: AsyncSession = Depends(get_session)):
    categories = await repo.top_categories(session)
    meta = PageMeta(
        title=f"Каталог металлопроката с ценами — купить в {city_prep()} | {settings.site_name}",
        description=f"Каталог металлопроката: арматура, трубы, уголок, швеллер, лист. Цены за метр и тонну, "
        f"доставка по {city_prep()} и области. ☎ {settings.phone}",
        h1="Каталог металлопроката",
        canonical=absolute("/catalog/"),
        robots=robots_for(request),
    )
    crumbs = [("Главная", "/"), CATALOG_ROOT]
    return templates.TemplateResponse(
        request,
        "catalog/index.html",
        {
            "meta": meta,
            "categories": categories,
            "breadcrumbs": crumbs,
            "jsonld": [jsonld.to_script(jsonld.breadcrumbs(crumbs))],
        },
    )


@router.get("/catalog/{path:path}/", response_class=HTMLResponse, name="catalog_node")
async def catalog_node(
    request: Request,
    path: str,
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    """Один адрес — три типа страниц: раздел, SEO-страница фильтра или товар."""
    if category := await repo.get_category(session, path):
        return await _render_category(request, session, category, page)
    if landing := await repo.get_landing(session, path):
        return await _render_landing(request, session, landing, page)
    if (product := await repo.get_product(session, path)) and page == 1:
        return await _render_product(request, session, product)
    raise HTTPException(status_code=404)


async def _render_category(request: Request, session: AsyncSession, category: Category, page: int):
    products = await repo.list_products(session, category.path, page=page, page_size=settings.page_size)
    if page > products.pages:
        raise HTTPException(status_code=404)
    min_kop = await repo.min_price_kop(session, category.path)
    crumbs = _crumbs(await repo.breadcrumb_categories(session, category.path))
    context = {
        "meta": category_meta(request, category, min_kop),
        "node": category,
        "children": await repo.child_categories(session, category),
        "landings": await repo.category_landings(session, category),
        "products": products,
        "breadcrumbs": crumbs,
        "jsonld": [
            jsonld.to_script(jsonld.breadcrumbs(crumbs)),
            jsonld.to_script(jsonld.item_list(products.items)),
        ],
    }
    return templates.TemplateResponse(request, "catalog/listing.html", context)


async def _render_landing(request: Request, session: AsyncSession, landing: FilterLanding, page: int):
    category = landing.category
    products = await repo.list_products(
        session, category.path, filters=landing.filters, page=page, page_size=settings.page_size
    )
    if page > products.pages:
        raise HTTPException(status_code=404)
    min_kop = await repo.min_price_kop(session, category.path, filters=landing.filters)
    crumbs = _crumbs(await repo.breadcrumb_categories(session, category.path), (landing.name, landing.url))
    siblings = [item for item in await repo.category_landings(session, category) if item.id != landing.id]
    context = {
        "meta": landing_meta(request, landing, min_kop),
        "node": landing,
        "children": [],
        "landings": siblings,
        "products": products,
        "breadcrumbs": crumbs,
        "jsonld": [
            jsonld.to_script(jsonld.breadcrumbs(crumbs)),
            jsonld.to_script(jsonld.item_list(products.items)),
        ],
    }
    return templates.TemplateResponse(request, "catalog/listing.html", context)


async def _render_product(request: Request, session: AsyncSession, product: Product):
    category_path = product.path.rsplit("/", 1)[0]
    crumbs = _crumbs(await repo.breadcrumb_categories(session, category_path), (product.name, product.url))
    context = {
        "meta": product_meta(request, product),
        "product": product,
        "breadcrumbs": crumbs,
        "jsonld": [jsonld.to_script(jsonld.breadcrumbs(crumbs)), jsonld.to_script(jsonld.product(product))],
    }
    return templates.TemplateResponse(request, "catalog/product.html", context)
