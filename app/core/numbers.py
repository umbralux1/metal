"""Числа для человека и от человека: «11,7» на сайте и в админке, Decimal в коде.

Единственное место, где точка меняется на запятую и обратно (`tests/test_numbers.py` следит). Проверки диапазонов
(«больше нуля», «не больше двух знаков») и тексты ошибок для покупателя — у полей, здесь только «что такое число».
"""

from decimal import Decimal, InvalidOperation


def format_decimal(value: Decimal | float | int | None) -> str:
    """11.700 → «11,7», 12.00 → «12», 0.8880 → «0,888», None → «». Без научной записи: 10, а не 1E+1."""
    if value is None:
        return ""
    return f"{Decimal(str(value)).normalize():f}".replace(".", ",")


def parse_decimal(raw: object) -> Decimal | None:
    """«11,7», «1 000», «1 000» (неразрывный пробел), « 5 » → Decimal. Пусто — None, не число — ValueError."""
    text = "".join(("" if raw is None else str(raw)).split()).replace(",", ".")  # split() убирает и неразрывный пробел
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"не число: {raw!r}") from None
    if not value.is_finite():
        raise ValueError(f"не число: {raw!r}")
    return value
