import pytest

from app.seo.hours import opening_hours

WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _plain(text: str) -> list[tuple[list[str], str, str]]:
    return [(s["dayOfWeek"], s["opens"], s["closes"]) for s in opening_hours(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Пн–Сб 9:00–19:00, Вс 10:00–15:00", [(WEEK[:6], "09:00", "19:00"), (["Sunday"], "10:00", "15:00")]),
        ("Пн-Пт 8:00-18:00; Сб 9-15; Вс — выходной", [(WEEK[:5], "08:00", "18:00"), (["Saturday"], "09:00", "15:00")]),
        ("Пн - Пт: с 9:00 до 18:00, Сб, Вс 10:00-16:00", [(WEEK[:5], "09:00", "18:00"), (WEEK[5:], "10:00", "16:00")]),
        ("пн.–пт. 9.00–18.00", [(WEEK[:5], "09:00", "18:00")]),
        ("Ежедневно 8:00–20:00", [(WEEK, "08:00", "20:00")]),
        ("Без выходных 8:00–24:00", [(WEEK, "08:00", "23:59")]),
        ("Круглосуточно", [(WEEK, "00:00", "23:59")]),
        # Одинаковые часы в разных записях — одной спецификацией
        ("Пн–Пт 9:00–18:00, Сб 9:00–18:00", [(WEEK[:6], "09:00", "18:00")]),
    ],
)
def test_opening_hours(text, expected):
    assert _plain(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Звоните, договоримся",
        "Пн–Сб 9:00–19:00, обед 13–14",  # «обед» не поняли — лучше без разметки, чем неверная
        "Пн–Сб 9:00–25:00",
        "Пн–Сб 9:00–19:00, Вс по договорённости",
    ],
)
def test_unclear_hours_give_nothing(text):
    assert opening_hours(text) == []
