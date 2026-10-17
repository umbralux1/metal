"""Корзина и оформление заказа. Страницы корзины не индексируются (robots.txt + X-Robots-Tag)."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart import store
from app.cart.store import CartItem
from app.catalog.calculator import CalcError, CalcResult, calculate, parse_input
from app.catalog.models import Product
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import format_rub, templates
from app.leads.models import Lead
from app.leads.notify import notify_new_lead
from app.leads.router import normalize_phone
from app.seo.meta import PageMeta, absolute

router = APIRouter()
NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}
DELIVERY = {"delivery": "Доставка", "pickup": "Самовывоз со склада"}


@dataclass
class Line:
    index: int
    item: CartItem
    product: Product | None
    calc: CalcResult | None
    error: str | None = None


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
            lines.append(Line(index, item, product, _calc(product, item)))
        except CalcError as exc:
            lines.append(Line(index, item, product, None, str(exc)))
    return lines


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
    total = sum(line.calc.total_kop for line in lines if line.calc)
    context = {
        "meta": _meta("Корзина"),
        "lines": lines,
        "total_kop": total,
        "has_errors": any(line.error for line in lines),
        "values": {"delivery": "delivery"},
        "delivery_options": DELIVERY,
    }
    return templates.TemplateResponse(request, "cart/page.html", context, headers=NOINDEX)


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
    form = await request.form()
    values = {k: str(form.get(k, "")).strip() for k in ("name", "phone", "comment", "delivery", "address")}
    if values["delivery"] not in DELIVERY:
        values["delivery"] = "delivery"
    items = store.load(request)
    lines = await _lines(session, items)
    total = sum(line.calc.total_kop for line in lines if line.calc)

    def page(error: str | None, status: int = 422):
        context = {
            "meta": _meta("Корзина"),
            "lines": lines,
            "total_kop": total,
            "has_errors": any(line.error for line in lines),
            "values": values,
            "delivery_options": DELIVERY,
            "error": error,
        }
        return templates.TemplateResponse(request, "cart/page.html", context, status_code=status, headers=NOINDEX)

    if form.get("website"):  # ловушка для ботов
        return RedirectResponse("/cart/", status_code=303)
    if not lines:
        return RedirectResponse("/cart/", status_code=303)
    if any(line.error for line in lines):
        return page("Исправьте позиции с ошибками или удалите их")
    phone = normalize_phone(values["phone"])
    if phone is None:
        return page("Проверьте номер телефона: нужен российский номер, например +7 916 123-45-67")
    if values["delivery"] == "delivery" and len(values["address"]) < 5:
        return page("Укажите адрес доставки — город, улицу, дом или участок")

    snapshot = [
        {
            "product_id": line.product.id,
            "name": line.product.name,
            "url": line.product.url,
            **line.item.params(),
            **line.calc.as_dict(),
        }
        for line in lines
    ]
    comment_parts = [DELIVERY[values["delivery"]]]
    if values["delivery"] == "delivery":
        comment_parts.append(values["address"][:300])
    if values["comment"]:
        comment_parts.append(values["comment"][:1500])
    lead = Lead(
        product_id=None,
        product_name=f"Корзина: {len(lines)} поз.",
        name=values["name"][:120],
        phone=phone,
        comment=". ".join(comment_parts),
        calc={
            "kind": "cart",
            "items": snapshot,
            "total_kop": total,
            "delivery": values["delivery"],
            "address": values["address"][:300],
        },
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)
    request.state.cart_count = 0  # в шапке страницы «Заказ принят» корзина уже пустая
    response = templates.TemplateResponse(
        request, "cart/done.html", {"meta": _meta("Заказ принят"), "lead": lead, "lines": lines}, headers=NOINDEX
    )
    store.save(response, request, [])  # корзина оформлена — очищаем
    return response
