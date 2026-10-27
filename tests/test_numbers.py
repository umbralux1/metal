"""Числа на сайте и в админке: одна функция показа и одна разбора (`app/core/numbers.py`).

Раньше «число → 11,7» было написано в 11 местах, а «11,7 → число» — в пяти, и копии разошлись: в цене «1 000»
понималось, в количестве с неразрывным пробелом (скопировали из Excel или с сайта) — нет, а корзина из-за своего
разбора задваивала строки (BUG-008). Здесь:
- что показывается и что понимается как число;
- одинаковое поведение во всех полях ввода — новое поле с числом добавить в `NUMBER_FIELDS`;
- охрана: вне `app/core/numbers.py` никто не меняет точку на запятую и обратно сам.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.admin.money import rub_to_kop
from app.cart.checkout import parse_distance_km
from app.cart.store import CartItem, add
from app.catalog.calculator import parse_input
from app.catalog.models import Product, Unit
from app.core.numbers import format_decimal, parse_decimal

APP = Path(__file__).resolve().parent.parent / "app"
NBSP = " "


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("12.00"), "12"),
        (Decimal("6.50"), "6,5"),
        (Decimal("0.8880"), "0,888"),
        (Decimal("11.700"), "11,7"),
        (Decimal("10"), "10"),  # без научной записи 1E+1
        (2.5, "2,5"),
        (3, "3"),
        (None, ""),
    ],
)
def test_format_decimal(value, text):
    assert format_decimal(value) == text


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("11,7", Decimal("11.7")),
        ("11.7", Decimal("11.7")),
        (" 5 ", Decimal("5")),
        ("1 000", Decimal("1000")),
        (f"1{NBSP}000", Decimal("1000")),  # неразрывный пробел — из Excel и с сайтов
        ("2,50", Decimal("2.50")),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_decimal(raw, value):
    assert parse_decimal(raw) == value


@pytest.mark.parametrize("raw", ["сорок", "1,2,3", "inf", "NaN", "12 мм"])
def test_parse_decimal_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


# Каждое поле, где человек вводит число: как достать из него разобранное значение
METER = Product(base_unit=Unit.METER)
NUMBER_FIELDS = {
    "calc_qty": lambda raw: parse_input({"unit": "m", "qty": raw}, METER).quantity,  # количество в калькуляторе
    "cut_length": lambda raw: parse_input({"cut": "1", "cut_len": raw}, METER).cut_length_m,  # длина отрезка
    "distance_km": lambda raw: parse_distance_km(raw),  # расстояние доставки
    "admin_price": lambda raw: Decimal(rub_to_kop(raw)) / 100,  # цена в админке
}
# Все значения подходят по диапазону каждому полю — проверяется только «что считается числом»
SAME_NUMBERS = [("11,7", Decimal("11.7")), (" 5 ", Decimal("5")), ("1 000", Decimal("1000")), (f"1{NBSP}000", 1000)]
SAME_IDS = ["comma", "padded", "space", "nbsp"]


@pytest.mark.parametrize(("raw", "value"), SAME_NUMBERS, ids=SAME_IDS)
@pytest.mark.parametrize("field", NUMBER_FIELDS)
def test_every_field_understands_numbers_the_same(field, raw, value):
    assert NUMBER_FIELDS[field](raw) == value


@pytest.mark.parametrize("raw", ["сорок", "1,2,3", "inf"])
@pytest.mark.parametrize("field", NUMBER_FIELDS)
def test_every_field_rejects_garbage(field, raw):
    with pytest.raises(ValueError):
        NUMBER_FIELDS[field](raw)


def test_same_item_with_spaced_quantity_merges_in_cart():
    """002:FR-003. BUG-008: «1 000» дважды — одна строка на 2000, а не две одинаковые строки."""
    item = lambda: CartItem(product_id=1, unit="m", qty="1 000")  # noqa: E731
    items = add(add([], item()), item())
    assert [(i.product_id, i.qty) for i in items] == [(1, "2000")]


# Свои замены точки на запятую и обратно — признак копии format_decimal / parse_decimal
OWN_NUMBER_FORMAT = re.compile(
    r"""\.replace\(\s*(["'])[.,]\1\s*,\s*(["'])[.,]\2\s*\)|replace\(\s*'\.'\s*,\s*','\s*\)"""
)


def test_numbers_are_formatted_and_parsed_only_in_core():
    found = [
        f"{path.relative_to(APP.parent)}:{n}: {line.strip()}"
        for path in sorted([*APP.rglob("*.py"), *APP.rglob("*.html")])
        if path != APP / "core" / "numbers.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if OWN_NUMBER_FORMAT.search(line)
    ]
    assert found == [], "числа — только через format_decimal / parse_decimal (app/core/numbers.py):\n" + "\n".join(
        found
    )
