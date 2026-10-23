"""Начальные тарифы доставки.

Кладутся только в пустую таблицу: цены, поправленные в админке, и удалённые машины при перезапуске
сервера не возвращаются. Запускается при каждом старте (app/bootstrap.py) и вручную:
python -m app.delivery.seed
"""

import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, engine
from app.delivery.models import DeliveryVehicle

RUB = 100  # копеек в рубле

DEFAULT_VEHICLES: list[dict[str, Any]] = [
    {
        "name": "Грузовик до 1,2 т",
        "max_weight_kg": 1200,
        "max_length_m": Decimal("3"),
        "base_price_kop": 1850 * RUB,
        "included_km": 5,
        "price_per_km_kop": 130 * RUB,
        "self_unloading": True,
        "sort": 10,
    },
    {
        "name": "Грузовик до 5 т",
        "max_weight_kg": 5000,
        "max_length_m": Decimal("6"),
        "base_price_kop": 2400 * RUB,
        "included_km": 10,
        "price_per_km_kop": 150 * RUB,
        "self_unloading": True,
        "sort": 20,
    },
    {
        "name": "Манипулятор до 10 т",
        "max_weight_kg": 10000,
        "max_length_m": Decimal("8"),
        "base_price_kop": 15000 * RUB,
        "included_km": 25,
        "price_per_km_kop": 190 * RUB,
        "self_unloading": False,
        "sort": 30,
    },
    {
        "name": "Длинномер до 25 т",
        "max_weight_kg": 25000,
        "max_length_m": Decimal("13.5"),
        "base_price_kop": 18500 * RUB,
        "included_km": 30,
        "price_per_km_kop": 180 * RUB,
        "self_unloading": True,
        "sort": 40,
    },
]


async def seed_vehicles(session: AsyncSession) -> int:
    """Начальные машины — только в пустую таблицу. Возвращает, сколько добавлено."""
    if await session.scalar(select(func.count()).select_from(DeliveryVehicle)):
        return 0
    session.add_all(DeliveryVehicle(**data) for data in DEFAULT_VEHICLES)
    await session.commit()
    return len(DEFAULT_VEHICLES)


async def main() -> None:
    async with SessionLocal() as session:
        added = await seed_vehicles(session)
    print(f"Машины доставки: добавлено {added}" if added else "Машины доставки: уже есть, не трогаю")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
