"""Калькулятор заказа: сколько метров, прутков и килограммов, сколько резов и сколько это стоит.

Чистые функции без БД — легко тестировать. Деньги в копейках, длины и вес в Decimal.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.catalog.models import Product, Unit
from app.core.numbers import format_decimal, parse_decimal

MAX_QUANTITY = Decimal(100_000)
MAX_CUTS = 10_000


class CalcError(ValueError):
    """Ошибка ввода, которую можно показать покупателю как есть."""


@dataclass
class CalcInput:
    unit: str = "pcs"  # "pcs" | "m" | "kg"
    quantity: Decimal | None = None
    cut: bool = False
    cut_length_m: Decimal | None = None
    cut_count: int | None = None


@dataclass
class CalcResult:
    meters: Decimal | None
    pieces: int | None
    weight_kg: Decimal | None
    price_unit: Unit
    price_kop: int
    material_kop: int
    cuts: int = 0
    cut_kop: int = 0
    waste_m: Decimal = Decimal(0)
    notes: list[str] = field(default_factory=list)

    @property
    def total_kop(self) -> int:
        return self.material_kop + self.cut_kop

    def as_dict(self) -> dict:
        """Снимок для сохранения в заявке."""
        return {
            "meters": _s(self.meters),
            "pieces": self.pieces,
            "weight_kg": _s(self.weight_kg),
            "price_unit": self.price_unit.value,
            "price_kop": self.price_kop,
            "material_kop": self.material_kop,
            "cuts": self.cuts,
            "cut_kop": self.cut_kop,
            "waste_m": _s(self.waste_m),
            "total_kop": self.total_kop,
        }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.normalize():f}"


def _kop(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _ceil_div(a: Decimal, b: Decimal) -> int:
    q = a / b
    return int(q) if q == int(q) else int(q) + 1


def _parse_decimal(raw: str | None, field_name: str) -> Decimal | None:
    try:
        return parse_decimal(raw)
    except ValueError:
        raise CalcError(f"{field_name}: введите число") from None


def parse_input(params: Mapping[str, str], product: Product) -> CalcInput:
    """Разбирает параметры формы (query string или form data)."""
    unit = params.get("unit") or default_unit(product)
    if unit not in {"pcs", "m", "kg"}:
        raise CalcError("Неизвестная единица")
    cut = params.get("cut") in {"1", "on", "true"}
    count_raw = _parse_decimal(params.get("cut_count"), "Количество отрезков")
    if count_raw is not None and count_raw != int(count_raw):
        raise CalcError("Количество отрезков: целое число")
    return CalcInput(
        unit=unit,
        quantity=_parse_decimal(params.get("qty"), "Количество"),
        cut=cut,
        cut_length_m=_parse_decimal(params.get("cut_len"), "Длина отрезка"),
        cut_count=int(count_raw) if count_raw is not None else None,
    )


def default_unit(product: Product) -> str:
    """В форме количество вводится в метрах; в штуках — только у товаров, которые продаются штуками.
    Штуки и килограммы по-прежнему принимаются от API и старых ссылок."""
    return "pcs" if product.base_unit == Unit.PIECE else "m"


def default_input(product: Product) -> CalcInput:
    """По умолчанию — один пруток / одна труба: длина прутка в метрах (или 1 м, 1 шт.)."""
    if default_unit(product) == "m" and product.length_m:
        return CalcInput(unit="m", quantity=Decimal(product.length_m).normalize())
    return CalcInput(unit=default_unit(product), quantity=Decimal(1))


def calculate(product: Product, inp: CalcInput, cut_price_kop: int, ton_from_kg: int) -> CalcResult:
    per_m = product.weight_per_m_kg
    notes: list[str] = []
    cuts = 0
    waste = Decimal(0)
    meters: Decimal | None  # без резки у листа и штучного товара метров нет, у товара без длины — штук
    pieces: int | None

    if inp.cut:
        meters, pieces, cuts, waste = _cutting(product, inp, notes)
    else:
        meters, pieces = _plain(product, inp, notes)

    weight = (meters * per_m).quantize(Decimal("0.01")) if meters is not None and per_m else None
    price_unit, price_kop, material_kop = _price(product, meters, pieces, weight, ton_from_kg, notes)

    return CalcResult(
        meters=meters,
        pieces=pieces,
        weight_kg=weight,
        price_unit=price_unit,
        price_kop=price_kop,
        material_kop=material_kop,
        cuts=cuts,
        cut_kop=cuts * cut_price_kop,
        waste_m=waste,
        notes=notes,
    )


def _plain(product: Product, inp: CalcInput, notes: list[str]) -> tuple[Decimal | None, int | None]:
    q = inp.quantity
    if q is None or q <= 0:
        raise CalcError("Укажите количество больше нуля")
    if q > MAX_QUANTITY:
        raise CalcError("Слишком большое количество — позвоните, посчитаем опт")
    bar = product.length_m

    if inp.unit == "pcs":
        if q != int(q):
            raise CalcError("Штуки — целое число")
        if not bar and product.base_unit != Unit.PIECE:
            raise CalcError("Этот товар продаётся на метры")
        pieces = int(q)
        return (pieces * bar if bar else None), pieces

    if inp.unit == "kg":
        if not product.weight_per_m_kg:
            raise CalcError("Для этого товара не указан вес метра")
        meters = q / product.weight_per_m_kg
    else:
        meters = q

    if not bar:
        return meters.quantize(Decimal("0.01")), None
    pieces = _ceil_div(meters, bar)
    rounded = pieces * bar
    if rounded != meters:
        notes.append(f"Округлили до целых: {pieces} шт. по {format_decimal(bar)} м. Нужно точнее — включите резку")
    return rounded, pieces


def _cutting(product: Product, inp: CalcInput, notes: list[str]) -> tuple[Decimal, int, int, Decimal]:
    bar = product.length_m
    length, count = inp.cut_length_m, inp.cut_count
    if not bar:
        raise CalcError("Резка в размер доступна для товаров в прутках и трубах")
    if length is None or length <= 0:
        raise CalcError("Укажите длину отрезка")
    if length > bar:
        raise CalcError(f"Отрезок длиннее прутка ({format_decimal(bar)} м)")
    if not count or count < 1:
        raise CalcError("Укажите количество отрезков")
    if count > MAX_CUTS:
        raise CalcError("Слишком много отрезков — позвоните, посчитаем")

    per_bar = int(bar // length)
    pieces = -(-count // per_bar)
    exact = bar - per_bar * length == 0
    full, rest = divmod(count, per_bar)
    # Из прутка без остатка последний отрезок получается без реза
    cuts = full * (per_bar - (1 if exact else 0)) + rest
    meters = pieces * bar
    waste = meters - count * length
    notes.append(f"{count} отр. по {format_decimal(length)} м из {pieces} шт. по {format_decimal(bar)} м")
    if waste > 0:
        notes.append(f"Обрезки {format_decimal(waste)} м отдаём вместе с заказом, в цену входит весь пруток")
    return meters, pieces, cuts, waste


def _price(
    product: Product,
    meters: Decimal | None,
    pieces: int | None,
    weight: Decimal | None,
    ton_from_kg: int,
    notes: list[str],
) -> tuple[Unit, int, int]:
    per_m = product.price_for(Unit.METER)
    per_t = product.price_for(Unit.TON)
    per_pc = product.price_for(Unit.PIECE)

    if product.base_unit == Unit.PIECE and per_pc and pieces is not None:
        return Unit.PIECE, per_pc.amount_kop, pieces * per_pc.amount_kop
    if per_t and weight is not None and weight >= ton_from_kg:
        notes.append(f"От {ton_from_kg // 1000} т действует цена за тонну")
        return Unit.TON, per_t.amount_kop, _kop(weight / 1000 * per_t.amount_kop)
    if per_m and meters is not None:
        return Unit.METER, per_m.amount_kop, _kop(meters * per_m.amount_kop)
    if per_t and weight is not None:
        return Unit.TON, per_t.amount_kop, _kop(weight / 1000 * per_t.amount_kop)
    raise CalcError("Цена по запросу — позвоните, сориентируем")
