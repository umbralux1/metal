"""Цена доставки по тарифу машины. Чистые функции: без базы, сети и настроек — всё приходит аргументами."""

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Tariff:
    """Тариф машины: базовая цена за первые included_km, дальше — price_per_km_kop за каждый начатый км."""

    base_price_kop: int
    included_km: int
    price_per_km_kop: int


class DistanceError(ValueError):
    """Расстояние, для которого цену не посчитать: отрицательное или дальше предела."""


def delivery_price_kop(tariff: Tariff, distance_km: Decimal | int, max_km: int) -> int:
    """Цена доставки в копейках. Неполный километр сверх включённых — как целый (10,3 км → 11)."""
    if distance_km < 0:
        raise DistanceError("Расстояние не может быть отрицательным")
    if distance_km > max_km:
        raise DistanceError(f"Дальше {max_km} км стоимость доставки уточнит менеджер")
    extra_km = math.ceil(max(Decimal(0), Decimal(distance_km) - tariff.included_km))
    return tariff.base_price_kop + extra_km * tariff.price_per_km_kop
