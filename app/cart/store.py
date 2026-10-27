"""Корзина в подписанной cookie: без регистрации и без таблиц в базе.

В cookie — только товар и параметры расчёта (единица, количество, резка). Цены и итоги не хранятся:
при каждом показе позиции пересчитываются калькулятором по текущим ценам. Подпись (SECRET_KEY) не даёт
подменить содержимое руками.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.numbers import format_decimal, parse_decimal

COOKIE = "cart"
MAX_ITEMS = 30  # cookie ограничена ~4 КБ
FULL_MESSAGE = f"В корзине уже {MAX_ITEMS} позиций — оформите заказ или позвоните нам"
MAX_AGE = 30 * 24 * 3600
PARAM_KEYS = ("unit", "qty", "cut", "cut_len", "cut_count")


@dataclass
class CartItem:
    product_id: int
    unit: str = "m"
    qty: str = ""
    cut: bool = False
    cut_len: str = ""
    cut_count: str = ""

    def params(self) -> dict[str, str]:
        """Параметры в том виде, в каком их принимает калькулятор (как из формы)."""
        data = {"unit": self.unit, "qty": self.qty, "cut_len": self.cut_len, "cut_count": self.cut_count}
        if self.cut:
            data["cut"] = "1"
        return {k: v for k, v in data.items() if v}

    def same_as(self, other: "CartItem") -> bool:
        """Та же позиция: тот же товар, единица и резка (длина отрезка «3,9» и «3.9» — одна и та же)."""
        return (self.product_id, self.unit, self.cut, _number(self.cut_len)) == (
            other.product_id,
            other.unit,
            other.cut,
            _number(other.cut_len),
        )

    @classmethod
    def from_form(cls, product_id: int, form: Mapping[str, object]) -> "CartItem":
        return cls(
            product_id=product_id,
            unit=str(form.get("unit") or "m")[:4],
            qty=str(form.get("qty") or "").strip()[:12],
            cut=str(form.get("cut") or "") in {"1", "on", "true"},
            cut_len=str(form.get("cut_len") or "").strip()[:12],
            cut_count=str(form.get("cut_count") or "").strip()[:6],
        )


def _number(raw: str) -> object:
    """Число для сравнения; не число — как есть (такие позиции склеиваются, только если строки совпадают)."""
    try:
        return parse_decimal(raw)
    except ValueError:
        return raw


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt="cart")


def load(request: Request) -> list[CartItem]:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return []
    try:
        data = _serializer().loads(raw)
        return [CartItem(**row) for row in data][:MAX_ITEMS]
    except (BadSignature, TypeError, ValueError):
        return []  # подделка, старый формат или смена SECRET_KEY — пустая корзина


def save(response: Response, request: Request, items: list[CartItem]) -> None:
    if not items:
        response.delete_cookie(COOKIE, path="/")
        return
    response.set_cookie(
        COOKIE,
        _serializer().dumps([asdict(i) for i in items[:MAX_ITEMS]]),
        max_age=MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def add(items: list[CartItem], item: CartItem) -> list[CartItem]:
    """Та же позиция складывается: без резки — количество, с той же резкой — число отрезков. Иначе — новая строка.

    Склеенную позицию проверяет вызывающий (`merged_with`): сумма может не считаться (больше допустимого).
    """
    for existing in items:
        if existing.same_as(item):
            try:
                if item.cut:
                    existing.cut_count = format_decimal(
                        (parse_decimal(existing.cut_count) or 0) + (parse_decimal(item.cut_count) or 0)
                    )
                else:
                    existing.qty = format_decimal((parse_decimal(existing.qty) or 0) + (parse_decimal(item.qty) or 0))
            except ValueError:
                break
            return items
    if len(items) >= MAX_ITEMS:
        raise ValueError(FULL_MESSAGE)
    return [*items, item]


def merged_with(items: list[CartItem], item: CartItem) -> CartItem:
    """Позиция корзины, в которую легла `item` после `add`: склеенная или сама `item`."""
    return next((existing for existing in items if existing.same_as(item)), item)


def count(request: Request) -> int:
    override = getattr(request.state, "cart_count", None)  # корзину изменили в этом же ответе
    return override if override is not None else len(load(request))
