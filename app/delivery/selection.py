"""Подбор машины под груз и подсказка «дешевле с резкой». Чистые функции: без базы, сети и настроек."""

from dataclasses import dataclass
from decimal import Decimal

from app.delivery.cargo import CargoSpec
from app.delivery.pricing import DistanceError, Tariff, delivery_price_kop


@dataclass(frozen=True)
class Vehicle:
    """Машина для подбора: сколько везёт, какой длины груз влезает и почём."""

    id: int
    name: str
    max_weight_kg: int
    max_length_m: Decimal
    self_unloading: bool
    tariff: Tariff


@dataclass(frozen=True)
class VehicleQuote:
    """Машина под конкретный заказ: влезает ли и сколько стоит. price_kop=None — цену не посчитать."""

    vehicle: Vehicle
    fits_weight: bool
    fits_length: bool
    price_kop: int | None

    @property
    def fits(self) -> bool:
        return self.fits_weight and self.fits_length


@dataclass(frozen=True)
class CutHint:
    """Если порезать заказ до cut_to_m, повезёт vehicle за price_kop вместо instead_kop."""

    vehicle: Vehicle
    cut_to_m: Decimal
    price_kop: int
    instead_kop: int


def quote_vehicles(
    vehicles: list[Vehicle], cargo: CargoSpec, distance_km: Decimal | None, max_km: int
) -> list[VehicleQuote]:
    """Каждая машина под груз, в том же порядке. Груз неизвестен — подходят все (подтвердит менеджер).

    Без расстояния или дальше max_km — без цены. Отрицательное расстояние — DistanceError.
    """
    if distance_km is not None and distance_km < 0:
        raise DistanceError("Расстояние не может быть отрицательным")
    return [
        VehicleQuote(
            vehicle=v,
            fits_weight=not cargo.complete or cargo.weight_kg <= v.max_weight_kg,
            fits_length=not cargo.complete or cargo.max_length_m <= v.max_length_m,
            price_kop=_price_or_none(v.tariff, distance_km, max_km),
        )
        for v in vehicles
    ]


def cheapest_fit(quotes: list[VehicleQuote]) -> VehicleQuote | None:
    """Самая дешёвая подходящая машина с посчитанной ценой."""
    priced = [q for q in quotes if q.fits and q.price_kop is not None]
    return min(priced, key=lambda q: q.price_kop or 0, default=None)


def cut_hint(quotes: list[VehicleQuote], min_length_m: Decimal) -> CutHint | None:
    """Машина дешевле, которую не пускает только длина, а заказ режется до её кузова (min_length_m — короче нельзя)."""
    best = cheapest_fit(quotes)
    if best is None or best.price_kop is None:
        return None
    candidates = [
        q
        for q in quotes
        if q.fits_weight
        and not q.fits_length
        and q.vehicle.max_length_m >= min_length_m
        and q.price_kop is not None
        and q.price_kop < best.price_kop
    ]
    cheaper = min(candidates, key=lambda q: q.price_kop or 0, default=None)
    if cheaper is None or cheaper.price_kop is None:
        return None
    return CutHint(cheaper.vehicle, cheaper.vehicle.max_length_m, cheaper.price_kop, best.price_kop)


def _price_or_none(tariff: Tariff, distance_km: Decimal | None, max_km: int) -> int | None:
    if distance_km is None or distance_km > max_km:
        return None
    return delivery_price_kop(tariff, distance_km, max_km)
