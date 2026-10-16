"""Часы работы из текста настройки WORK_HOURS → openingHoursSpecification для schema.org.

Один источник правды: на сайте показывается тот же текст, из которого собирается разметка.
Понимает «Пн–Сб 9:00–19:00, Вс 10:00–15:00», «Пн-Пт 8:00-18:00; Сб 9-15», «Ежедневно 8:00–20:00»,
«Круглосуточно», «Вс — выходной». Не понял хоть часть строки — разметки нет совсем: лучше без неё,
чем «закрыто» в выдаче в день, когда склад работает.
"""

import logging
import re
from typing import Any

log = logging.getLogger("metal.seo")

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_TOKENS = {
    "пн": 0, "понедельник": 0,
    "вт": 1, "вторник": 1,
    "ср": 2, "среда": 2,
    "чт": 3, "четверг": 3,
    "пт": 4, "пятница": 4,
    "сб": 5, "суббота": 5,
    "вс": 6, "воскресенье": 6,
}  # fmt: skip
EVERY_DAY = ("ежедневно", "без выходных", "каждый день")

_DASH = r"\s*[–—\-]\s*"
_DAY = r"(?:" + "|".join(sorted(DAY_TOKENS, key=len, reverse=True)) + r")\.?"
_DAYS = rf"{_DAY}(?:(?:{_DASH}|\s*,\s*|\s+){_DAY})*"
_TIME = r"(\d{1,2})(?:[:.](\d{2}))?"
_GROUP = re.compile(
    rf"(?P<days>{_DAYS}|{'|'.join(EVERY_DAY)})\s*:?\s*(?:с\s*)?{_TIME}(?:{_DASH}|\s*до\s*){_TIME}",
    re.IGNORECASE,
)
_DAY_OFF = re.compile(rf"{_DAYS}\s*(?:[–—\-:]\s*)?(?:выходной|выходные|закрыто)", re.IGNORECASE)
_ROUND_THE_CLOCK = re.compile(r"^\s*(?:ежедневно\s*,?\s*)?круглосуточно\s*$", re.IGNORECASE)


def _days(text: str) -> list[int]:
    """«Пн–Сб» → 0..5, «Сб, Вс» → [5, 6], «ежедневно» → все дни."""
    text = text.lower()
    if text in EVERY_DAY:
        return list(range(7))
    found: list[int] = []
    text = re.sub(_DASH, "-", text)
    for part in re.split(r"[\s,]+", text):
        bounds = [DAY_TOKENS[t.strip(".")] for t in part.split("-") if t.strip(".")]
        if len(bounds) == 2:
            start, end = bounds
            span = range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
            found += span
        elif bounds:
            found += bounds
    return found


def _time(hours: str, minutes: str | None) -> str | None:
    h, m = int(hours), int(minutes or 0)
    if h == 24 and m == 0:
        return "23:59"  # конец суток так понимают и Google, и Яндекс
    if h > 23 or m > 59:
        return None
    return f"{h:02d}:{m:02d}"


def opening_hours(text: str) -> list[dict[str, Any]]:
    """Спецификации по дням; дни с одинаковыми часами — одной записью."""
    if not text.strip():
        return []
    if _ROUND_THE_CLOCK.match(text):
        return [_spec(list(range(7)), "00:00", "23:59")]

    schedule: dict[int, tuple[str, str]] = {}
    rest = text
    for match in _GROUP.finditer(text):
        opens, closes = _time(match[2], match[3]), _time(match[4], match[5])
        days = _days(match["days"].strip())
        if not opens or not closes or not days:
            return _give_up(text)
        for day in days:
            schedule[day] = (opens, closes)
        rest = rest.replace(match[0], " ", 1)
    rest = _DAY_OFF.sub(" ", rest)
    # Остались цифры или дни недели — значит, часть строки не поняли
    if re.search(r"\d", rest) or re.search(rf"(?<![а-яё]){_DAY}(?![а-яё])", rest, re.IGNORECASE) or not schedule:
        return _give_up(text)

    groups: dict[tuple[str, str], list[int]] = {}
    for day in sorted(schedule):
        groups.setdefault(schedule[day], []).append(day)
    return [_spec(days, opens, closes) for (opens, closes), days in groups.items()]


def _spec(days: list[int], opens: str, closes: str) -> dict[str, Any]:
    return {
        "@type": "OpeningHoursSpecification",
        "dayOfWeek": [DAYS[d] for d in days],
        "opens": opens,
        "closes": closes,
    }


def _give_up(text: str) -> list[dict[str, Any]]:
    log.warning(
        "WORK_HOURS «%s» не разобран — часы в разметку не попадут. Пример: «Пн–Сб 9:00–19:00, Вс 10:00–15:00»", text
    )
    return []
