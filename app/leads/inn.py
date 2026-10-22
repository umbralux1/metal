"""ИНН: проверка по контрольным цифрам. 10 цифр — организация, 12 — ИП."""

WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def is_valid_inn(inn: str) -> bool:
    """Верный ли ИНН: только цифры, 10 или 12 знаков, контрольные цифры сходятся, не одни нули."""
    if not inn.isdigit() or len(inn) not in (10, 12) or set(inn) == {"0"}:
        return False
    digits = [int(c) for c in inn]
    if len(digits) == 10:
        return _check_digit(digits, WEIGHTS_10) == digits[9]
    return _check_digit(digits, WEIGHTS_11) == digits[10] and _check_digit(digits, WEIGHTS_12) == digits[11]


def _check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10
