"""Админка заявок: заявки с карточек и заказы из корзины с таблицей позиций и доставкой."""

from markupsafe import Markup
from sqladmin import ModelView
from wtforms import SelectField

from app.cart.checkout import PAYMENTS
from app.core.templating import format_local_time, format_rub
from app.leads.models import Lead

LEAD_STATUSES = [("new", "Новая"), ("in_progress", "В работе"), ("done", "Выполнена"), ("spam", "Спам")]


def _lead_calc_html(calc: dict) -> Markup:
    """Расчёт заявки для карточки в админке: позиции корзины списком или итог одного товара."""
    if calc.get("kind") != "cart":
        total = calc.get("total_kop")
        parts = [
            f"{calc.get('pieces')} шт." if calc.get("pieces") else "",
            f"{calc.get('meters')} м" if calc.get("meters") else "",
        ]
        details = ", ".join(p for p in parts if p)
        return Markup("{} {}").format(
            format_rub(total) if total is not None else "—", f"({details})" if details else ""
        )
    rows = Markup("").join(
        Markup(
            "<tr><td><a href='{}' target='_blank'>{}</a></td><td>{}</td><td>{}</td>"
            "<td style='text-align:right'>{}</td></tr>"
        ).format(
            item.get("url", ""),
            item.get("name", ""),
            ", ".join(
                x
                for x in (
                    f"{item.get('pieces')} шт." if item.get("pieces") else "",
                    f"{item.get('meters')} м" if item.get("meters") else "",
                )
                if x
            ),
            f"резка {item.get('cut_count')} × {item.get('cut_len')} м" if item.get("cut") else "",
            format_rub(item.get("total_kop")),
        )
        for item in calc.get("items", [])
    )
    delivery = "Доставка: " + calc.get("address", "") if calc.get("delivery") == "delivery" else "Самовывоз"
    table = Markup(
        "<table class='table table-sm'><thead><tr><th>Товар</th><th>Количество</th><th>Резка</th>"
        "<th>Сумма</th></tr></thead>"
        "<tbody>{}</tbody></table>"
    ).format(rows)
    if "goods_kop" not in calc:  # заявки до доставки с выбором машины
        return table + Markup("<p><strong>Итого: {}</strong> · {}</p>").format(
            format_rub(calc.get("total_kop")), delivery
        )
    return table + Markup(
        "<p>{}</p><p>{}</p><p>Оплата: {}</p><p>Товары: {} · Доставка: {} · <strong>Итого: {}</strong></p>"
    ).format(
        _lead_delivery_text(calc, delivery),
        _lead_buyer_text(calc.get("buyer") or {}),
        PAYMENTS.get(calc.get("payment", "cash"), "—"),
        format_rub(calc["goods_kop"]),
        format_rub(calc["delivery_kop"]) if calc.get("delivery_kop") is not None else "уточнить",
        format_rub(calc.get("total_kop")),
    )


def _lead_delivery_text(calc: dict, delivery: str) -> str:
    """«Доставка: адрес · Грузовик до 5 т, 18 км — 3 600 ₽»; без машины — подберёт менеджер."""
    if calc.get("delivery") != "delivery":
        return delivery
    vehicle = calc.get("vehicle")
    if not vehicle:
        km = f"{calc['distance_km']} км — " if calc.get("distance_km") else ""
        return f"{delivery} · {km}машину и рейсы подобрать менеджеру"
    price = format_rub(vehicle["price_kop"]) if vehicle.get("price_kop") is not None else "стоимость уточнит менеджер"
    return f"{delivery} · {vehicle['name']}, {vehicle['distance_km']} км — {price}"


def _lead_buyer_text(buyer: dict) -> str:
    if buyer.get("type") == "company":
        return f"Покупатель: {buyer.get('company_name', '')}, ИНН {buyer.get('inn', '')}"
    return "Покупатель: частное лицо"


class LeadAdmin(ModelView, model=Lead):
    name = "Заявка"
    name_plural = "Заявки"
    icon = "fa-solid fa-phone"
    category = "Продажи"
    page_size = 50

    column_list = [Lead.id, Lead.created_at, Lead.product_name, Lead.name, Lead.phone, Lead.calc, Lead.status]
    column_details_list = [
        Lead.id,
        Lead.created_at,
        Lead.product_name,
        Lead.name,
        Lead.phone,
        Lead.comment,
        Lead.calc,
        Lead.status,
    ]
    column_labels = {
        "id": "№",
        "created_at": "Когда",
        "product_name": "Товар",
        "name": "Имя",
        "phone": "Телефон",
        "calc": "Сумма",
        "status": "Статус",
        "comment": "Комментарий",
    }
    column_searchable_list = [Lead.phone, Lead.name, Lead.product_name]
    column_sortable_list = [Lead.id, Lead.created_at, Lead.status]
    column_default_sort = [(Lead.created_at, True)]
    column_formatters = {
        Lead.calc: lambda m, a: format_rub(m.calc.get("total_kop")) if m.calc else "—",
        Lead.status: lambda m, a: dict(LEAD_STATUSES).get(m.status, m.status),
        Lead.created_at: lambda m, a: format_local_time(m.created_at),
    }
    column_formatters_detail = {
        Lead.created_at: lambda m, a: format_local_time(m.created_at),
        Lead.status: lambda m, a: dict(LEAD_STATUSES).get(m.status, m.status),
        Lead.calc: lambda m, a: _lead_calc_html(m.calc or {}),
    }
    can_create = False
    form_columns = [Lead.status, Lead.comment]
    form_overrides = {"status": SelectField}
    form_args = {"status": {"choices": LEAD_STATUSES}}
