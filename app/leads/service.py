"""Заявки для других модулей: создание заявки и её номер со снимком расчёта для страниц «принята»."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import Lead
from app.leads.notify import notify_new_lead


@dataclass(frozen=True)
class NewLead:
    """Заявка до сохранения: с карточки товара (product_id) или из корзины (product_id=None)."""

    product_id: int | None
    product_name: str
    name: str
    phone: str
    comment: str
    calc: dict[str, Any]


@dataclass(frozen=True)
class LeadReceipt:
    id: int
    calc: dict[str, Any]


async def create_lead(session: AsyncSession, new: NewLead) -> LeadReceipt:
    """Сохраняет заявку и уведомляет менеджера. Телефон уже проверен (normalize_phone)."""
    lead = Lead(
        product_id=new.product_id,
        product_name=new.product_name,
        name=new.name,
        phone=new.phone,
        comment=new.comment,
        calc=new.calc,
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)
    return LeadReceipt(id=lead.id, calc=dict(lead.calc or {}))
