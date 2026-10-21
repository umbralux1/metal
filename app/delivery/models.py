from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class DeliveryVehicle(TimestampMixin, Base):
    """Машина доставки и её тариф: базовая цена за первые N км, дальше — цена за каждый километр.

    Деньги в копейках, как цены товаров. Грузоподъёмность и длина кузова решают, какие машины
    подходят под заказ (прутки 11,7 м в «Газель» не влезут).
    """

    __tablename__ = "delivery_vehicles"
    __table_args__ = (
        CheckConstraint("max_weight_kg > 0", name="max_weight_positive"),
        CheckConstraint("max_length_m > 0", name="max_length_positive"),
        CheckConstraint("base_price_kop >= 0", name="base_price_not_negative"),
        CheckConstraint("included_km >= 0", name="included_km_not_negative"),
        CheckConstraint("price_per_km_kop >= 0", name="price_per_km_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    max_weight_kg: Mapped[int] = mapped_column(Integer)
    max_length_m: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    base_price_kop: Mapped[int] = mapped_column(Integer)
    included_km: Mapped[int] = mapped_column(Integer)
    price_per_km_kop: Mapped[int] = mapped_column(Integer)
    # Водитель только привозит, выгружает покупатель (у манипулятора — кран, выгрузка входит)
    self_unloading: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __str__(self) -> str:
        return self.name or "Новая машина"
