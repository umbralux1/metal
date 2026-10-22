"""Груз корзины для подбора машины: общий вес и самая длинная позиция. Чистые функции, без базы.

app.delivery.cargo.CargoSpec — что доставка получает на вход (про корзину и товары она не знает).
app.cart.cargo — корзина переводит свои позиции в CargoSpec:
- line_cargo(product, inp, result) — одна позиция: вес из калькулятора или штуки × «Вес 1 шт.»,
  длина — пруток, отрезок при резке или «Длина 1 шт.»;
- total_cargo(parts) — сумма весов, самая длинная позиция, complete=False, если хоть что-то неизвестно.
"""

from decimal import Decimal as D

import pytest

from app.cart.cargo import line_cargo, total_cargo
from app.catalog.calculator import CalcInput, calculate
from app.catalog.models import Price, Product, Unit
from app.delivery.cargo import CargoSpec


@pytest.fixture
def rebar() -> Product:
    """Арматура 12 мм: пруток 11,7 м, 0,888 кг/м."""
    return Product(
        name="Арматура 12 мм",
        length_m=D("11.7"),
        weight_per_m_kg=D("0.888"),
        base_unit=Unit.METER,
        prices=[Price(unit=Unit.METER, amount_kop=4325), Price(unit=Unit.TON, amount_kop=4870000)],
    )


@pytest.fixture
def sheet() -> Product:
    """Лист 2 мм 1250×2500: 49,1 кг, длинная сторона 2,5 м, продаётся штуками."""
    return Product(
        name="Лист 2 мм 1250х2500",
        weight_per_piece_kg=D("49.1"),
        piece_length_m=D("2.5"),
        base_unit=Unit.PIECE,
        prices=[Price(unit=Unit.PIECE, amount_kop=300000)],
    )


def cargo(product: Product, **kw) -> CargoSpec:
    inp = CalcInput(**kw)
    return line_cargo(product, inp, calculate(product, inp, 5000, 1000))


def test_rebar_by_meters_is_whole_bars(rebar):
    # 100 м → 9 прутков по 11,7 м = 105,3 м × 0,888 кг = 93,51 кг; везти пруток целиком
    assert cargo(rebar, unit="m", quantity=D(100)) == CargoSpec(D("93.51"), D("11.7"), True)


def test_rebar_cut_is_as_long_as_the_piece(rebar):
    # 10 отрезков по 2 м — длина груза 2 м, а не 11,7: влезет в маленький грузовик
    spec = cargo(rebar, unit="m", cut=True, cut_length_m=D(2), cut_count=10)
    assert spec.max_length_m == D(2)
    assert spec.weight_kg == D("20.78")  # 2 прутка × 11,7 м × 0,888 — обрезки едут вместе с заказом
    assert spec.complete


def test_sheets_by_pieces(sheet):
    assert cargo(sheet, unit="pcs", quantity=D(20)) == CargoSpec(D("982.0"), D("2.5"), True)


def test_piece_without_weight_is_incomplete(sheet):
    sheet.weight_per_piece_kg = None
    spec = cargo(sheet, unit="pcs", quantity=D(5))
    assert spec.complete is False
    assert spec.max_length_m == D("2.5")  # длина известна — её всё равно учитываем


def test_piece_without_length_is_incomplete(sheet):
    sheet.piece_length_m = None
    spec = cargo(sheet, unit="pcs", quantity=D(5))
    assert spec.complete is False
    assert spec.weight_kg == D("245.5")


def test_meter_product_without_bar_length_is_incomplete():
    hose = Product(
        name="Без длины прутка",
        weight_per_m_kg=D(1),
        base_unit=Unit.METER,
        prices=[Price(unit=Unit.METER, amount_kop=100)],
    )
    assert cargo(hose, unit="m", quantity=D(10)).complete is False


def test_total_sums_weight_and_takes_longest():
    parts = [CargoSpec(D("93.51"), D("11.7"), True), CargoSpec(D("982.0"), D("2.5"), True)]
    assert total_cargo(parts) == CargoSpec(D("1075.51"), D("11.7"), True)


def test_total_is_incomplete_if_any_part_is():
    parts = [CargoSpec(D(100), D(6), True), CargoSpec(D(0), D(0), False)]
    total = total_cargo(parts)
    assert total.complete is False
    assert (total.weight_kg, total.max_length_m) == (D(100), D(6))  # известная часть сохраняется


def test_total_of_nothing_is_empty_and_complete():
    assert total_cargo([]) == CargoSpec(D(0), D(0), True)


def test_cargo_spec_is_immutable():
    spec = CargoSpec(D(1), D(1), True)
    with pytest.raises(AttributeError):
        spec.weight_kg = D(2)  # type: ignore[misc]
