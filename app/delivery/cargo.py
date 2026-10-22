"""Груз заказа — то, что доставка получает на вход. Про корзину и товары доставка не знает."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CargoSpec:
    """Вес заказа и самая длинная позиция. complete=False — что-то неизвестно, машину подтвердит менеджер."""

    weight_kg: Decimal
    max_length_m: Decimal
    complete: bool
