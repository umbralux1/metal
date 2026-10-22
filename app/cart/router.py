"""Корзина и оформление заказа. Страницы корзины не индексируются (robots.txt + X-Robots-Tag)."""

from dataclasses import dataclass
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import store
from app.cart.cargo import line_cargo, line_cut_down_length_m, total_cargo, total_cut_down_length_m
from app.cart.checkout import BUYER_TYPES, DELIVERY, PAYMENTS, CheckoutError, CheckoutForm, parse_distance_km
from app.cart.store import CartItem
from app.catalog.calculator import CalcError, CalcInput, CalcResult, calculate, parse_input
from app.catalog.models import Product
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import format_rub, templates
from app.delivery.cargo import CargoSpec
from app.delivery.selection import CutHint, VehicleQuote, cut_hint, quote_vehicles
from app.delivery.service import list_active_vehicles
from app.leads.models import Lead
from app.leads.notify import notify_new_lead
from app.seo.meta import PageMeta, absolute

router = APIRouter()
NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


@dataclass
class Line:
    index: int
    item: CartItem
    product: Product | None
    calc: CalcResult | None
    error: str | None = None
    inp: CalcInput | None = None


@dataclass(frozen=True)
class DeliveryOptions:
    """Машины под груз корзины на странице: цены, недоступные машины, подсказка про резку."""

    distance_km: Decimal | None
    distance_error: str | None
    cargo: CargoSpec
    quotes: list[VehicleQuote]
    hint: CutHint | None
    max_km: int

    @property
    def any_fits(self) -> bool:
        return any(q.fits for q in self.quotes)

    @property
    def beyond_max(self) -> bool:
        return self.distance_km is not None and self.distance_km > self.max_km


def _calc(product: Product, item: CartItem) -> CalcResult:
    return calculate(product, parse_input(item.params(), product), settings.cut_price_kop, settings.ton_price_from_kg)


async def _lines(session: AsyncSession, items: list[CartItem]) -> list[Line]:
    ids = {i.product_id for i in items}
    products = {p.id: p for p in await session.scalars(select(Product).where(Product.id.in_(ids)))} if ids else {}
    lines = []
    for index, item in enumerate(items):
        product = products.get(item.product_id)
        if product is None or not product.is_active:
            lines.append(Line(index, item, product, None, "Товар больше не продаётся — удалите его из корзины"))
            continue
        try:
            inp = parse_input(item.params(), product)
            result = calculate(product, inp, settings.cut_price_kop, settings.ton_price_from_kg)
            lines.append(Line(index, item, product, result, inp=inp))
        except CalcError as exc:
            lines.append(Line(index, item, product, None, str(exc)))
    return lines


async def _delivery_options(session: AsyncSession, lines: list[Line], distance_raw: str) -> DeliveryOptions:
    """Груз корзины → машины с ценами на это расстояние и подсказка «дешевле с резкой»."""
    ok = [(line.product, line.inp, line.calc) for line in lines if line.product and line.inp and line.calc]
    cargo = total_cargo(line_cargo(product, inp, result) for product, inp, result in ok)
    try:
        distance, error = parse_distance_km(distance_raw), None
    except CheckoutError as exc:
        distance, error = None, str(exc)
    quotes = quote_vehicles(await list_active_vehicles(session), cargo, distance, settings.delivery_max_km)
    shortest = total_cut_down_length_m(line_cut_down_length_m(product, inp) for product, inp, _ in ok)
    hint = cut_hint(quotes, shortest) if cargo.complete and shortest is not None else None
    return DeliveryOptions(distance, error, cargo, quotes, hint, settings.delivery_max_km)


def _cart_context(lines: list[Line], options: DeliveryOptions, values: dict[str, str]) -> dict:
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
    }


def _meta(h1: str) -> PageMeta:
    return PageMeta(
        title=f"{h1} | {settings.site_name}",
        description="",
        h1=h1,
        canonical=absolute("/cart/"),
        robots="noindex, nofollow",
    )


def _summary(result: CalcResult | None) -> str:
    if result is None:
        return ""
    parts = []
    if result.pieces:
        parts.append(f"{result.pieces} шт.")
    if result.meters:
        parts.append(f"{result.meters.normalize():f}".replace(".", ",") + " м")
    return " · ".join(parts)


def _is_fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


@router.post("/cart/add/", include_in_schema=False)
async def cart_add(request: Request, session: AsyncSession = Depends(get_session)):
    form = await request.form()
    try:
        product_id = int(str(form.get("product_id") or 0))
    except ValueError:
        product_id = 0
    product = await session.get(Product, product_id)
    item = CartItem.from_form(product_id, form)
    error = None
    result: CalcResult | None = None
    if product is None or not product.is_active:
        error = "Товар не найден, обновите страницу"
    else:
        try:
            result = _calc(product, item)  # не кладём в корзину то, что не считается («0 м», резка длиннее прутка)
            items = store.add(store.load(request), item)
        except (CalcError, ValueError) as exc:
            error = str(exc)

    if _is_fetch(request):
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=422, headers=NOINDEX)
        # Что добавили — для всплывающего уведомления: «25 шт. · 300 м · 12 975 ₽»
        added = {
            "ok": True,
            "count": len(items),
            "name": product.name,
            "summary": _summary(result),
            "total": format_rub(result.total_kop) if result else "",
        }
        response = JSONResponse(added, headers=NOINDEX)
    else:
        if error:
            target = f"{product.url}#calc" if product else "/cart/"
            return RedirectResponse(target, status_code=303)
        response = RedirectResponse("/cart/", status_code=303)
    store.save(response, request, items)
    return response


@router.get("/cart/", response_class=HTMLResponse, include_in_schema=False)
async def cart_page(request: Request, session: AsyncSession = Depends(get_session)):
    lines = await _lines(session, store.load(request))
    distance = str(request.query_params.get("distance_km", ""))[:20]
    options = await _delivery_options(session, lines, distance)
    values = CheckoutForm(distance_km=distance).model_dump()
    return templates.TemplateResponse(request, "cart/page.html", _cart_context(lines, options, values), headers=NOINDEX)


@router.post("/cart/update/", include_in_schema=False)
async def cart_update(request: Request):
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
async def cart_remove(request: Request):
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
async def cart_checkout(request: Request, session: AsyncSession = Depends(get_session)):
    raw = await request.form()
    form = CheckoutForm.from_form({k: str(v) for k, v in raw.items()})
    values = form.model_dump()  # как ввёл покупатель — для повторного показа формы
    lines = await _lines(session, store.load(request))
    options = await _delivery_options(session, lines, form.distance_km)

    def page(error: str):
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
        quote = _chosen_vehicle(form, options)
    except CheckoutError as exc:
        return page(str(exc))

    goods_kop = sum(line.calc.total_kop for line in lines if line.calc)
    calc: dict = {
        "kind": "cart",
        "items": [
            {
                "product_id": line.product.id,
                "name": line.product.name,
                "url": line.product.url,
                **line.item.params(),
                **line.calc.as_dict(),
            }
            for line in lines
            if line.product and line.calc
        ],
        "delivery": form.delivery,
        "address": form.address if form.delivery == "delivery" else "",
        "buyer": form.buyer(),
        "payment": form.payment,
        "goods_kop": goods_kop,
        "delivery_kop": 0,
    }
    if form.delivery == "delivery":
        distance = form.distance()
        calc["vehicle"] = quote and {
            "id": quote.vehicle.id,
            "name": quote.vehicle.name,
            "distance_km": f"{distance.normalize():f}" if distance is not None else None,
            "price_kop": quote.price_kop,
        }
        calc["delivery_kop"] = quote.price_kop if quote else None
    calc["total_kop"] = goods_kop + (calc["delivery_kop"] or 0)

    comment_parts = [DELIVERY[form.delivery]]
    if form.delivery == "delivery":
        comment_parts.append(form.address)
    if form.comment:
        comment_parts.append(form.comment)
    lead = Lead(
        product_id=None,
        product_name=f"Корзина: {len(lines)} поз.",
        name=form.name,
        phone=form.phone,
        comment=". ".join(comment_parts),
        calc=calc,
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)
    request.state.cart_count = 0  # в шапке страницы «Заказ принят» корзина уже пустая
    context = {"meta": _meta("Заказ принят"), "lead": lead, "lines": lines, "payments": PAYMENTS}
    response = templates.TemplateResponse(request, "cart/done.html", context, headers=NOINDEX)
    store.save(response, request, [])  # корзина оформлена — очищаем
    return response


def _chosen_vehicle(form: CheckoutForm, options: DeliveryOptions) -> VehicleQuote | None:
    """Выбранная машина. Не выбрана, выключена или не берёт груз — CheckoutError; ни одна не берёт — None."""
    if form.delivery != "delivery" or not options.any_fits:
        return None
    quote = next((q for q in options.quotes if str(q.vehicle.id) == form.vehicle_id), None)
    if quote is None:
        raise CheckoutError("Выберите машину для доставки")
    if not quote.fits:
        raise CheckoutError(f"Машина «{quote.vehicle.name}» не подходит для этого заказа — выберите другую")
    return quote
