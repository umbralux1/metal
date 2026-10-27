"""Телефон покупателя: приведение к одному виду."""

import re


def normalize_phone(raw: str) -> str | None:
    """«8 (916) 123-45-67» → «+79161234567», «495 123-45-67» → «+74951234567». None — не российский номер.

    Любые 10 цифр без кода страны — российский номер (мобильный или городской), как в маске «+7 (___) ___-__-__».
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return None
