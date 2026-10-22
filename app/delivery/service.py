"""Публичный интерфейс доставки для других модулей: машины из базы — в модели чтения."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.models import DeliveryVehicle
from app.delivery.pricing import Tariff
from app.delivery.selection import Vehicle


async def list_active_vehicles(session: AsyncSession) -> list[Vehicle]:
    """Машины, которые предлагаем покупателям, в порядке «Порядок» (от маленькой к большой)."""
    rows = await session.scalars(
        select(DeliveryVehicle).where(DeliveryVehicle.is_active).order_by(DeliveryVehicle.sort, DeliveryVehicle.id)
    )
    return [
        Vehicle(
            id=row.id,
            name=row.name,
            max_weight_kg=row.max_weight_kg,
            max_length_m=row.max_length_m,
            self_unloading=row.self_unloading,
            tariff=Tariff(row.base_price_kop, row.included_km, row.price_per_km_kop),
        )
        for row in rows
    ]
