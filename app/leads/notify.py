"""Куда уходят заявки. Сейчас — в лог. Telegram или почту подключать здесь."""

import logging

from app.core.templating import format_rub
from app.leads.models import Lead

logger = logging.getLogger("metal.leads")


async def notify_new_lead(lead: Lead) -> None:
    total = lead.calc.get("total_kop")
    logger.info(
        "Новая заявка #%s: %s, %s %s, сумма %s, комментарий: %s",
        lead.id,
        lead.product_name,
        lead.name or "без имени",
        lead.phone,
        format_rub(total) if total is not None else "—",
        lead.comment or "—",
    )
