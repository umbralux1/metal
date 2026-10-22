"""Груз корзины для подбора машины: вес и самая длинная позиция. Чистые функции, без базы."""

from collections.abc import Iterable
from decimal import Decimal

from app.catalog.calculator import CalcInput, CalcResult
from app.catalog.models import Product
from app.delivery.cargo import CargoSpec


def line_cargo(product: Product, inp: CalcInput, result: CalcResult) -> CargoSpec:
    """Груз одной позиции. Вес — из калькулятора или штуки × «Вес 1 шт.»; длина — пруток, отрезок или штука."""
    weight = result.weight_kg
    if weight is None and result.pieces is not None and product.weight_per_piece_kg:
        weight = result.pieces * product.weight_per_piece_kg
    length: Decimal | None
    if inp.cut and inp.cut_length_m:
        length = inp.cut_length_m  # обрезки короче отрезка и едут вместе с ним
    else:
        length = product.length_m or product.piece_length_m
    return CargoSpec(
        weight_kg=weight or Decimal(0),
        max_length_m=length or Decimal(0),
        complete=weight is not None and length is not None,
    )


def total_cargo(parts: Iterable[CargoSpec]) -> CargoSpec:
    """Груз всей корзины: веса складываются, длина — самой длинной позиции."""
    items = list(parts)
    return CargoSpec(
        weight_kg=sum((p.weight_kg for p in items), Decimal(0)),
        max_length_m=max((p.max_length_m for p in items), default=Decimal(0)),
        complete=all(p.complete for p in items),
    )


def line_cut_down_length_m(product: Product, inp: CalcInput) -> Decimal | None:
    """До какой длины позицию можно укоротить резкой: пруток — до любой, лист и свая — нет. None — неизвестно."""
    if inp.cut and inp.cut_length_m:
        return inp.cut_length_m
    if product.length_m:
        return Decimal(0)
    return product.piece_length_m


def total_cut_down_length_m(parts: Iterable[Decimal | None]) -> Decimal | None:
    """Самая короткая длина, до которой можно укоротить весь заказ. Хоть одна позиция неизвестна — None."""
    lengths = list(parts)
    if any(length is None for length in lengths):
        return None
    return max((length for length in lengths if length is not None), default=Decimal(0))
