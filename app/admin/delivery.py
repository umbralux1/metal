"""Раздел «Доставка → Машины»: машины и тарифы. Цены в форме в рублях, в базе — копейки."""

from decimal import Decimal, InvalidOperation
from typing import Any

from sqladmin import ModelView
from sqlalchemy import select
from starlette.requests import Request
from wtforms import Form, StringField
from wtforms.validators import InputRequired, NumberRange

from app.admin.money import kop_to_rub, rub_to_kop
from app.core.db import SessionLocal
from app.core.templating import format_decimal, format_rub
from app.delivery.models import DeliveryVehicle

# Поле формы в рублях → колонка в копейках: (поле, колонка, подпись, подсказка, ошибка, если пусто)
PRICE_FIELDS = (
    ("base_price_rub", "base_price_kop", "Базовая цена, ₽", "Например 1 850 или 1 850,50.", "Укажите базовую цену"),
    (
        "price_per_km_rub",
        "price_per_km_kop",
        "Цена за км сверх включённых, ₽",
        "Например 130. 0 — без доплаты за километры.",
        "Укажите цену за км (0 — без доплаты)",
    ),
)


def parse_length_m(raw: Any) -> Decimal:
    """«4,2» → Decimal("4.2"). Длина груза в метрах, больше нуля, не больше двух знаков после запятой."""
    text = str(raw or "").replace(",", ".").strip()
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Длина груза «{raw}»: введите число, например 6 или 13,5") from None
    if not value.is_finite() or value <= 0:
        raise ValueError("Длина груза должна быть больше 0")
    if value != value.quantize(Decimal("0.01")) or value >= 1000:
        raise ValueError(f"Длина груза «{raw}»: не больше двух знаков после запятой и меньше 1000 м")
    return value


class DeliveryVehicleAdmin(ModelView, model=DeliveryVehicle):  # type: ignore[call-arg]
    name = "Машина"
    name_plural = "Машины"
    icon = "fa-solid fa-truck"
    category = "Доставка"

    column_list = [
        DeliveryVehicle.name,
        DeliveryVehicle.max_weight_kg,
        DeliveryVehicle.max_length_m,
        DeliveryVehicle.base_price_kop,
        DeliveryVehicle.included_km,
        DeliveryVehicle.price_per_km_kop,
        DeliveryVehicle.is_active,
    ]
    column_labels = {
        "name": "Название",
        "max_weight_kg": "Грузоподъёмность, кг",
        "max_length_m": "Длина груза, м",
        "base_price_kop": "Базовая цена",
        "included_km": "Включено, км",
        "price_per_km_kop": "За км сверх",
        "self_unloading": "Выгрузка силами покупателя",
        "sort": "Порядок",
        "is_active": "Активна",
    }
    column_formatters = {
        DeliveryVehicle.base_price_kop: lambda m, a: format_rub(m.base_price_kop),
        DeliveryVehicle.price_per_km_kop: lambda m, a: format_rub(m.price_per_km_kop),
        DeliveryVehicle.max_length_m: lambda m, a: format_decimal(m.max_length_m),
    }
    column_default_sort = [(DeliveryVehicle.sort, False)]
    column_sortable_list = [DeliveryVehicle.name, DeliveryVehicle.sort]

    form_columns = [
        DeliveryVehicle.name,
        DeliveryVehicle.max_weight_kg,
        DeliveryVehicle.max_length_m,
        DeliveryVehicle.included_km,
        DeliveryVehicle.self_unloading,
        DeliveryVehicle.sort,
        DeliveryVehicle.is_active,
    ]
    form_overrides = {"max_length_m": StringField}  # «13,5» с запятой; разбирает parse_length_m
    form_args = {
        "max_weight_kg": {
            "validators": [InputRequired(), NumberRange(min=1, message="Грузоподъёмность должна быть больше 0")],
            "description": "Больше этого веса машина не повезёт.",
        },
        "max_length_m": {
            "validators": [InputRequired()],
            "description": "Самый длинный груз, который влезает в кузов. Прутки 11,7 м — только длинномер.",
        },
        "included_km": {
            "validators": [
                InputRequired(),
                NumberRange(min=0, message="Число включённых км не может быть отрицательным"),
            ],
            "description": "Сколько километров входит в базовую цену.",
        },
        "self_unloading": {"description": "Водитель только привозит. У манипулятора — нет: свой кран."},
        "sort": {"description": "Порядок карточек: меньше — выше. Шаг 10, чтобы вставлять между."},
        "is_active": {"description": "Снимите, чтобы не предлагать машину покупателям. Удалять не нужно."},
    }
    # Машину не удаляем: старые заказы ссылаются на неё. Снимите «Активна»
    can_delete = False

    async def scaffold_form(self, rules: Any = None) -> type[Form]:
        """Стандартная форма + цены в рублях: базовая после длины груза, за км — после включённых км."""
        base = await super().scaffold_form(rules)
        anchors = (base.max_length_m.creation_counter, base.included_km.creation_counter)
        extra = {}
        for (field, _column, label, hint, required), anchor in zip(PRICE_FIELDS, anchors, strict=True):
            unbound = StringField(
                label,
                validators=[InputRequired(message=required)],
                description=hint,
                render_kw={"inputmode": "decimal", "autocomplete": "off", "class": "form-control"},
            )
            unbound.creation_counter = anchor + 0.5  # порядок полей в форме
            extra[field] = unbound
        return type("DeliveryVehicleForm", (base,), extra)

    async def get_form_data_for_edit(self, obj: DeliveryVehicle) -> dict[str, Any]:
        data: dict[str, Any] = await super().get_form_data_for_edit(obj)
        for field, column, *_ in PRICE_FIELDS:
            data[field] = kop_to_rub(getattr(obj, column))
        data["max_length_m"] = format_decimal(obj.max_length_m)
        return data

    async def on_model_change(
        self, data: dict[str, Any], model: DeliveryVehicle, is_created: bool, request: Request
    ) -> None:
        for field, column, _label, _hint, required in PRICE_FIELDS:
            kop = rub_to_kop(data.pop(field, None), allow_zero=True)
            if kop is None:  # одни пробелы проходят InputRequired
                raise ValueError(required)
            data[column] = kop
        data["max_length_m"] = parse_length_m(data.get("max_length_m"))
        data["name"] = str(data.get("name") or "").strip()
        async with SessionLocal() as session:
            same_name = select(DeliveryVehicle.id).where(DeliveryVehicle.name == data["name"])
            if not is_created:
                same_name = same_name.where(DeliveryVehicle.id != model.id)
            if await session.scalar(same_name):
                raise ValueError(f"Машина «{data['name']}» уже есть")
