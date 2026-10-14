from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import repository as repo
from app.catalog.calculator import CalcError, calculate, default_input, parse_input
from app.catalog.landings import product_seo_text
from app.catalog.models import Category, FilterLanding, Product
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import templates
from app.seo import jsonld
from app.seo.meta import (
    PageMeta,
    absolute,
    category_meta,
    city_prep,
    landing_meta,
    piece_price_kop,
    product_meta,
    robots_for,
)

router = APIRouter()

CATALOG_ROOT = ("Каталог", "/catalog/")


def _crumbs(categories: list[Category | FilterLanding], tail: tuple[str, str] | None = None) -> list[tuple[str, str]]:
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


@router.get("/search/", response_class=HTMLResponse, name="search")
async def search(request: Request, q: str = "", session: AsyncSession = Depends(get_session)):
    query = q.strip()[:100]
    found = await repo.search_products(session, query) if query else []
    products = repo.ProductPage(items=found, total=len(found), page=1, pages=1)
    meta = PageMeta(
        title=f"Поиск «{query}» | {settings.site_name}" if query else f"Поиск по каталогу | {settings.site_name}",
        description="",
        h1=f"Поиск «{query}»" if query else "Поиск по каталогу",
        canonical=absolute("/search/"),
        robots="noindex, follow",
    )
    context = {"meta": meta, "q": query, "products": products}
    return templates.TemplateResponse(request, "search.html", context)


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
    if target := await repo.inactive_parent_url(session, path):
        return RedirectResponse(target, status_code=301)
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
    crumbs = _crumbs(await repo.breadcrumb_nodes(session, category.path), (landing.name, landing.url))
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


def _calc_context(product: Product, params) -> dict:
    """Расчёт для карточки: по параметрам формы или по умолчанию (1 пруток / 1 метр)."""
    has_input = any(k in params for k in ("qty", "cut", "unit"))
    try:
        inp = parse_input(params, product) if has_input else default_input(product)
        result = calculate(product, inp, settings.cut_price_kop, settings.ton_price_from_kg)
        return {"calc": result, "calc_error": None, "params": params if has_input else _params_from(inp)}
    except CalcError as exc:
        return {"calc": None, "calc_error": str(exc), "params": params}


def _params_from(inp) -> dict:
    qty = f"{inp.quantity.normalize():f}".replace(".", ",") if inp.quantity is not None else ""
    return {"unit": inp.unit, "qty": qty}


@router.get("/api/calc/{product_id}/", response_class=HTMLResponse, include_in_schema=False)
async def calc_partial(request: Request, product_id: int, session: AsyncSession = Depends(get_session)):
    """Кусок HTML с итогом — для пересчёта на лету без перезагрузки страницы."""
    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404)
    context = {"product": product, **_calc_context(product, request.query_params)}
    response = templates.TemplateResponse(request, "catalog/_calc_result.html", context)
    response.headers["X-Robots-Tag"] = "noindex"
    return response


async def _render_product(request: Request, session: AsyncSession, product: Product):
    parent_path = product.path.rsplit("/", 1)[0]
    crumbs = _crumbs(await repo.breadcrumb_nodes(session, parent_path), (product.name, product.url))
    size = await repo.size_landing(session, product)
    # Соседние размеры — посадочные того же раздела, что и посадочная товара
    neighbour_category = size.category if size else product.category
    neighbours = [
        item for item in await repo.category_landings(session, neighbour_category) if not size or item.id != size.id
    ]
    context = {
        "meta": product_meta(request, product),
        "product": product,
        "size": size,
        "same_size": await repo.same_size_products(session, size, product) if size else [],
        "neighbours": neighbours,
        "piece_kop": piece_price_kop(product),
        "auto_text": None if product.seo_text else product_seo_text(product),
        **_calc_context(product, request.query_params),
        "breadcrumbs": crumbs,
        "jsonld": [jsonld.to_script(jsonld.breadcrumbs(crumbs)), jsonld.to_script(jsonld.product(product))],
    }
    return templates.TemplateResponse(request, "catalog/product.html", context)
