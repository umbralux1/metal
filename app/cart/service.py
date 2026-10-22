"""Корзина: позиции с ценами, машины под груз корзины, оформление заказа в заявку."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cart.cargo import line_cargo, line_cut_down_length_m, total_cargo, total_cut_down_length_m
from app.cart.checkout import CheckoutError, CheckoutForm, order_comment, order_snapshot, parse_distance_km
from app.cart.store import CartItem
from app.catalog.calculator import CalcError, CalcInput, CalcResult, calculate, parse_input
from app.catalog.models import Product
from app.core.config import settings
from app.delivery.cargo import CargoSpec
from app.delivery.selection import CutHint, VehicleQuote, cut_hint, quote_vehicles
from app.delivery.service import list_active_vehicles
from app.leads.models import Lead
from app.leads.notify import notify_new_lead


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


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


def price_cart_item(product: Product, item: CartItem) -> CalcResult:
    """Цена позиции по текущим ценам. Не считается («0 м», резка длиннее прутка) — CalcError."""
    return calculate(product, parse_input(item.params(), product), settings.cut_price_kop, settings.ton_price_from_kg)


async def list_cart_lines(session: AsyncSession, items: list[CartItem]) -> list[Line]:
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


async def quote_cart_delivery(session: AsyncSession, lines: list[Line], distance_raw: str) -> DeliveryOptions:
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


async def create_order(
    session: AsyncSession, form: CheckoutForm, lines: list[Line], quote: VehicleQuote | None
) -> Lead:
    """Сохраняет заказ заявкой и уведомляет менеджера. Форма и машина уже проверены."""
    items = [
        {
            "product_id": line.product.id,
            "name": line.product.name,
            "url": line.product.url,
            **line.item.params(),
            **line.calc.as_dict(),
        }
        for line in lines
        if line.product and line.calc
    ]
    goods_kop = sum(line.calc.total_kop for line in lines if line.calc)
    lead = Lead(
        product_id=None,
        product_name=f"Корзина: {len(lines)} поз.",
        name=form.name,
        phone=form.phone,
        comment=order_comment(form),
        calc=order_snapshot(form, items, goods_kop, quote),
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)
    return lead
