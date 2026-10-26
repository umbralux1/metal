"""Деньги в формах админки: рубли в поле, копейки в базе."""

from decimal import Decimal
from typing import Any

from app.core.numbers import parse_decimal


def rub_to_kop(raw: Any, allow_zero: bool = False) -> int | None:
    """«43,25» / «48 700» / «48700.5» → копейки. Пусто — None. Мусор — понятная ошибка.

    allow_zero — для тарифов доставки: 0 ₽ за км значит «без доплаты».
    """
    try:
        value = parse_decimal(str(raw or "").replace("₽", ""))  # знак рубля — только в ценах
    except ValueError:
        raise ValueError(f"Цена «{raw}»: введите число, например 43,25") from None
    if value is None:
        return None
    if allow_zero and value.is_finite() and value < 0:
        raise ValueError(f"Цена «{raw}»: не может быть отрицательной")
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"Цена «{raw}»: должна быть больше нуля")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError(f"Цена «{raw}»: не больше двух знаков после запятой")
    if value >= 100_000_000:
        raise ValueError(f"Цена «{raw}»: слишком большая")
    return int(value * 100)


def kop_to_rub(kop: int) -> str:
    """4325 → «43,25», 4870000 → «48700» — для поля формы (без пробелов, чтобы легко править)."""
    rub, rest = divmod(kop, 100)
    return f"{rub},{rest:02d}" if rest else str(rub)
