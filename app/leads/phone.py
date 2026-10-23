"""Телефон покупателя: приведение к одному виду."""

import re


def normalize_phone(raw: str) -> str | None:
    """«8 (916) 123-45-67» → «+79161234567». None, если номер не похож на российский."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    return None
