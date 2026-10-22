"""Форма оформления заказа: проверка на входе (Pydantic), дальше — проверенные данные."""

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, model_validator

from app.leads.inn import is_valid_inn
from app.leads.router import normalize_phone

DELIVERY = {"delivery": "Доставка", "pickup": "Самовывоз со склада"}
BUYER_TYPES = {"person": "Частное лицо", "company": "Организация или ИП"}
PAYMENTS = {"cash": "Наличными или картой при получении", "invoice": "По счёту"}
MAX_DISTANCE_INPUT_KM = Decimal(10_000)  # дальше — опечатка; предел расчёта — DELIVERY_MAX_KM


class CheckoutError(ValueError):
    """Ошибка в форме — текст показываем покупателю как есть."""


def parse_distance_km(raw: str) -> Decimal | None:
    """«18», «18,5» → Decimal. Пусто — None. Не число или отрицательное — CheckoutError."""
    text = raw.strip().replace(",", ".").replace(" ", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise CheckoutError("Расстояние: введите число, например 18") from None
    if not value.is_finite():
        raise CheckoutError("Расстояние: введите число, например 18")
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
