"""Заявки для других модулей: создание заявки и её номер со снимком расчёта для страниц «принята».

Порог: не больше settings.lead_limit заявок с одного адреса за settings.lead_limit_minutes (specs/001-lead-rate-limit).
Счёт — по сохранённым заявкам в базе, поэтому общий для всех копий сайта и не обнуляется при перезапуске.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.leads.fingerprint import client_fingerprint
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
    client_ip: str  # адрес подключения; в базу попадает только отпечаток


class TooManyLeads(Exception):
    """С адреса уже принято settings.lead_limit заявок за окно — заявка не сохранена, менеджер не уведомлён.

    Текст исключения — сообщение покупателю.
    """


@dataclass(frozen=True)
class LeadReceipt:
    id: int
    calc: dict[str, Any]


async def create_lead(session: AsyncSession, new: NewLead) -> LeadReceipt:
    """Сохраняет заявку и уведомляет менеджера. Телефон уже проверен (normalize_phone).

    Порог достигнут — TooManyLeads. Проверка и сохранение — в одной транзакции под блокировкой по отпечатку:
    вторая одновременная заявка с того же адреса ждёт первую и видит её в счёте.
    """
    fingerprint = client_fingerprint(new.client_ip, settings.secret_key)
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(fingerprint))))
    since = func.now() - func.make_interval(0, 0, 0, 0, 0, settings.lead_limit_minutes)  # по часам базы
    recent = await session.scalar(
        select(func.count()).select_from(Lead).where(Lead.client_hash == fingerprint, Lead.created_at > since)
    )
    if (recent or 0) >= settings.lead_limit:
        # Блокировку снимет конец транзакции: сессия запроса закрывается после ответа. Откат здесь не делаем —
        # он сбросил бы загруженные товары, а они нужны, чтобы показать форму с ошибкой
        raise TooManyLeads(f"Слишком много заявок. Попробуйте через несколько минут или позвоните: {settings.phone}")
    lead = Lead(
        product_id=new.product_id,
        product_name=new.product_name,
        name=new.name,
        phone=new.phone,
        comment=new.comment,
        calc=new.calc,
        client_hash=fingerprint,
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)
    return LeadReceipt(id=lead.id, calc=dict(lead.calc or {}))
