"""Подзадача 7: проверка ИНН по контрольным цифрам. app.leads.inn.is_valid_inn — чистая функция.

ИНН организации — 10 цифр, ИП — 12. Последние цифры — контрольные: опечатка в одной цифре ловится.
"""

import pytest

from app.leads.inn import is_valid_inn


@pytest.mark.parametrize("inn", ["7707083893", "7736207543", "500100732259"])
def test_valid(inn):
    assert is_valid_inn(inn)


@pytest.mark.parametrize(
    "inn",
    [
        "7707083894",  # опечатка в контрольной цифре
        "500100732258",
        "123",
        "77070838931",  # 11 цифр — такого ИНН нет
        "770708389a",
        "",
        "0000000000",  # контрольная цифра сходится, но ИНН из нулей не бывает
    ],
)
def test_invalid(inn):
    assert not is_valid_inn(inn)
