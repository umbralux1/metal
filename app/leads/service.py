"""Заявка для страниц «Заявка принята» и «Заказ принят»: номер и снимок расчёта, без связи с базой."""

from dataclasses import dataclass
from typing import Any

from app.leads.models import Lead


@dataclass(frozen=True)
class LeadReceipt:
    id: int
    calc: dict[str, Any]


def lead_receipt(lead: Lead) -> LeadReceipt:
    return LeadReceipt(id=lead.id, calc=dict(lead.calc or {}))
