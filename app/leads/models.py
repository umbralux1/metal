from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Lead(TimestampMixin, Base):
    """Заявка с сайта. Расчёт сохраняется снимком: цены потом меняются, а заявка — нет."""

    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_client_hash_created_at", "client_hash", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    product_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    calc: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new", index=True)
    # Отпечаток адреса подключения (app/leads/fingerprint.py) — для счёта заявок; сам адрес не храним
    client_hash: Mapped[str | None] = mapped_column(String(32))

    def __str__(self) -> str:
        return f"Заявка №{self.id}: {self.product_name}, {self.phone}"
