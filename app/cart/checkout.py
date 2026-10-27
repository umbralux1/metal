"""Форма оформления заказа: проверка на входе (Pydantic), дальше — проверенные данные."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.core.numbers import parse_decimal
from app.delivery.selection import VehicleQuote
from app.leads.inn import is_valid_inn
from app.leads.phone import normalize_phone

DELIVERY = {"delivery": "Доставка", "pickup": "Самовывоз со склада"}
BUYER_TYPES = {"person": "Частное лицо", "company": "Организация или ИП"}
PAYMENTS = {"cash": "Наличными или картой при получении", "invoice": "По счёту"}
MAX_DISTANCE_INPUT_KM = Decimal(10_000)  # дальше — опечатка; предел расчёта — DELIVERY_MAX_KM


class CheckoutError(ValueError):
    """Ошибка в форме — текст показываем покупателю как есть."""


def parse_distance_km(raw: str) -> Decimal | None:
    """«18», «18,5» → Decimal. Пусто — None. Не число или отрицательное — CheckoutError."""
    try:
        value = parse_decimal(raw)
    except ValueError:
        raise CheckoutError("Расстояние: введите число, например 18") from None
    if value is None:
        return None
    if value < 0:
        raise CheckoutError("Расстояние не может быть отрицательным")
    if value > MAX_DISTANCE_INPUT_KM:
        raise CheckoutError("Проверьте расстояние: больше 10 000 км")
    return value.quantize(Decimal("0.1"))


class CheckoutForm(BaseModel):
    """Поля формы как пришли (строки), после проверки — нормализованные: телефон +7…, ИНН без пробелов."""

    name: str = ""
    phone: str = ""
    comment: str = ""
    delivery: Literal["delivery", "pickup"] = "delivery"
    address: str = ""
    distance_km: str = ""
    vehicle_id: str = ""
    buyer_type: Literal["person", "company"] = "person"
    company_name: str = ""
    inn: str = ""
    payment: Literal["cash", "invoice"] = "cash"

    @classmethod
    def from_form(cls, form: dict[str, str]) -> "CheckoutForm":
        """Из данных формы: лишнее отбрасываем, неизвестные варианты выбора — по умолчанию."""
        data = {k: str(form.get(k, "")).strip() for k in cls.model_fields}
        data = {k: v for k, v in data.items() if v}
        if data.get("delivery") not in DELIVERY:
            data.pop("delivery", None)
        if data.get("buyer_type") not in BUYER_TYPES:
            data.pop("buyer_type", None)
        if data.get("payment") not in PAYMENTS:
            data.pop("payment", None)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def _limit_lengths(self) -> "CheckoutForm":
        self.name, self.address, self.comment = self.name[:120], self.address[:300], self.comment[:1500]
        self.company_name, self.inn = self.company_name[:200], self.inn[:20]
        return self

    def check(self) -> None:
        """Проверка по порядку полей формы; первая ошибка — CheckoutError. Машину проверяет корзина по базе."""
        phone = normalize_phone(self.phone)
        if phone is None:
            raise CheckoutError("Проверьте номер телефона: нужен российский номер, например +7 916 123-45-67")
        self.phone = phone
        if self.delivery == "delivery":
            if len(self.address) < 5:
                raise CheckoutError("Укажите адрес доставки — город, улицу, дом или участок")
            if self.distance() is None:
                raise CheckoutError("Укажите расстояние до объекта, км")
        if self.buyer_type == "company":
            if not self.company_name:
                raise CheckoutError("Укажите название организации")
            inn = self.inn.replace(" ", "")
            if not is_valid_inn(inn):
                raise CheckoutError("Проверьте ИНН: 10 цифр у организации, 12 у ИП")
            self.inn = inn
        elif self.payment == "invoice":
            raise CheckoutError("Оплата по счёту — для организаций и ИП")

    def distance(self) -> Decimal | None:
        """Расстояние, км, — только для доставки."""
        return parse_distance_km(self.distance_km) if self.delivery == "delivery" else None

    def buyer(self) -> dict[str, str]:
        """Покупатель для снимка в заявке."""
        if self.buyer_type == "company":
            return {"type": "company", "company_name": self.company_name, "inn": self.inn}
        return {"type": "person"}


def choose_vehicle(form: CheckoutForm, quotes: list[VehicleQuote]) -> VehicleQuote | None:
    """Выбранная машина. Не выбрана, выключена или не берёт груз — CheckoutError; ни одна не берёт — None."""
    if form.delivery != "delivery" or not any(q.fits for q in quotes):
        return None
    quote = next((q for q in quotes if str(q.vehicle.id) == form.vehicle_id), None)
    if quote is None:
        raise CheckoutError("Выберите машину для доставки")
    if not quote.fits:
        raise CheckoutError(f"Машина «{quote.vehicle.name}» не подходит для этого заказа — выберите другую")
    return quote


def order_snapshot(
    form: CheckoutForm, items: list[dict[str, Any]], goods_kop: int, quote: VehicleQuote | None
) -> dict[str, Any]:
    """Снимок заказа для заявки (`Lead.calc`): позиции, доставка, покупатель, суммы в копейках."""
    calc: dict[str, Any] = {
        "kind": "cart",
        "items": items,
        "delivery": form.delivery,
        "address": form.address if form.delivery == "delivery" else "",
        "buyer": form.buyer(),
        "payment": form.payment,
        "goods_kop": goods_kop,
        "delivery_kop": 0,
    }
    if form.delivery == "delivery":
        distance = form.distance()
        distance_km = f"{distance.normalize():f}" if distance is not None else None
        calc["distance_km"] = distance_km  # и без машины: менеджер подбирает рейсы на это расстояние
        calc["vehicle"] = quote and {
            "id": quote.vehicle.id,
            "name": quote.vehicle.name,
            "distance_km": distance_km,
            "price_kop": quote.price_kop,
        }
        calc["delivery_kop"] = quote.price_kop if quote else None
    calc["total_kop"] = goods_kop + (calc["delivery_kop"] or 0)
    return calc


def order_comment(form: CheckoutForm) -> str:
    """Комментарий заявки: способ получения, адрес, комментарий покупателя."""
    parts = [DELIVERY[form.delivery]]
    if form.delivery == "delivery":
        parts.append(form.address)
    if form.comment:
        parts.append(form.comment)
    return ". ".join(parts)
