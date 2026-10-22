"""Корзина и оформление заказа. Страницы корзины не индексируются (robots.txt + X-Robots-Tag)."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import store
from app.cart.checkout import BUYER_TYPES, DELIVERY, PAYMENTS, CheckoutError, CheckoutForm, choose_vehicle
from app.cart.service import (
    DeliveryOptions,
    Line,
    create_order,
    get_product,
    list_cart_lines,
    price_cart_item,
    quote_cart_delivery,
)
from app.cart.store import CartItem
from app.catalog.calculator import CalcError, CalcResult
from app.core.config import settings
from app.core.db import get_session
from app.core.maps import yandex_map
from app.core.templating import format_rub, templates
from app.seo.meta import PageMeta, absolute

router = APIRouter()
NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def _cart_context(lines: list[Line], options: DeliveryOptions, values: dict[str, str]) -> dict[str, Any]:
    return {
        "meta": _meta("Корзина"),
        "lines": lines,
        "total_kop": sum(line.calc.total_kop for line in lines if line.calc),
        "has_errors": any(line.error for line in lines),
        "values": values,
        "delivery_options": DELIVERY,
        "buyer_types": BUYER_TYPES,
        "payments": PAYMENTS,
        "options": options,
        "map": yandex_map(),
    }


def _meta(h1: str) -> PageMeta:
    return PageMeta(
        title=f"{h1} | {settings.site_name}",
        description="",
        h1=h1,
        canonical=absolute("/cart/"),
        robots="noindex, nofollow",
    )


def _summary(result: CalcResult) -> str:
    parts = []
    if result.pieces:
        parts.append(f"{result.pieces} шт.")
    if result.meters:
        parts.append(f"{result.meters.normalize():f}".replace(".", ",") + " м")
    return " · ".join(parts)


def _is_fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


@router.post("/cart/add/", include_in_schema=False)
async def cart_add(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    form = await request.form()
    try:
        product_id = int(str(form.get("product_id") or 0))
    except ValueError:
        product_id = 0
    product = await get_product(session, product_id)
    item = CartItem.from_form(product_id, form)
    try:
        if product is None or not product.is_active:
            raise ValueError("Товар не найден, обновите страницу")
        result = price_cart_item(product, item)  # не кладём в корзину то, что не считается
        items = store.add(store.load(request), item)
    except (CalcError, ValueError) as exc:
        if _is_fetch(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422, headers=NOINDEX)
        return RedirectResponse(f"{product.url}#calc" if product else "/cart/", status_code=303)

    response: Response
    if _is_fetch(request):
        # Что добавили — для всплывающего уведомления: «25 шт. · 300 м · 12 975 ₽»
        added = {
            "ok": True,
            "count": len(items),
            "name": product.name,
            "summary": _summary(result),
            "total": format_rub(result.total_kop),
        }
        response = JSONResponse(added, headers=NOINDEX)
    else:
        response = RedirectResponse("/cart/", status_code=303)
    store.save(response, request, items)
    return response


@router.get("/cart/", response_class=HTMLResponse, include_in_schema=False)
async def cart_page(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    lines = await list_cart_lines(session, store.load(request))
    distance = str(request.query_params.get("distance_km", ""))[:20]
    options = await quote_cart_delivery(session, lines, distance)
    values = CheckoutForm(distance_km=distance).model_dump()
    return templates.TemplateResponse(request, "cart/page.html", _cart_context(lines, options, values), headers=NOINDEX)


@router.post("/cart/update/", include_in_schema=False)
async def cart_update(request: Request) -> Response:
    form = await request.form()
    items = store.load(request)
    try:
        index = int(str(form.get("index")))
        items[index].qty = str(form.get("qty") or "").strip()[:12]
    except (ValueError, IndexError):
        pass
    response = RedirectResponse("/cart/", status_code=303)
    store.save(response, request, items)
    return response


@router.post("/cart/remove/", include_in_schema=False)
async def cart_remove(request: Request) -> Response:
    form = await request.form()
    items = store.load(request)
    try:
        items.pop(int(str(form.get("index"))))
    except (ValueError, IndexError):
        pass
    response = RedirectResponse("/cart/", status_code=303)
    store.save(response, request, items)
    return response


@router.post("/cart/checkout/", response_class=HTMLResponse, include_in_schema=False)
async def cart_checkout(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    raw = await request.form()
    form = CheckoutForm.from_form({k: str(v) for k, v in raw.items()})
    values = form.model_dump()  # как ввёл покупатель — для повторного показа формы
    lines = await list_cart_lines(session, store.load(request))
    options = await quote_cart_delivery(session, lines, form.distance_km)

    def page(error: str) -> Response:
        context = {**_cart_context(lines, options, values), "error": error}
        return templates.TemplateResponse(request, "cart/page.html", context, status_code=422, headers=NOINDEX)

    if raw.get("website"):  # ловушка для ботов
        return RedirectResponse("/cart/", status_code=303)
    if not lines:
        return RedirectResponse("/cart/", status_code=303)
    if any(line.error for line in lines):
        return page("Исправьте позиции с ошибками или удалите их")
    try:
        form.check()
        quote = choose_vehicle(form, options.quotes)
    except CheckoutError as exc:
        return page(str(exc))

    lead = await create_order(session, form, lines, quote)
    request.state.cart_count = 0  # в шапке страницы «Заказ принят» корзина уже пустая
    context = {"meta": _meta("Заказ принят"), "lead": lead, "lines": lines, "payments": PAYMENTS}
    response = templates.TemplateResponse(request, "cart/done.html", context, headers=NOINDEX)
    store.save(response, request, [])  # корзина оформлена — очищаем
    return response
