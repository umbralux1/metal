"""Генератор посадочных «по размеру» из номенклатуры каталога по правилам из landing_rules.py.

Запуск: python -m app.catalog.landings (на хостинге — сам при каждом старте, в админке — «Обновить из каталога»).

- Создаёт посадочные под размеры, которые есть в товарах, с title, description, H1 и текстом из данных товаров.
- Обновляет свои (is_generated) посадочные: тексты, фильтр, «в индексе».
- Размер пропал или товаров стало меньше порога — страница не удаляется, а получает noindex (адрес не ломается).
- Ручные посадочные не трогает. Посадочная, которую поправили в админке, становится ручной.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.landing_rules import RULES, LandingRule
from app.catalog.models import Category, FilterLanding, Product, Unit
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.templating import format_rub
from app.seo.meta import PRICE_TOKEN


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"создано {len(self.created)}, обновлено {len(self.updated)}, скрыто из индекса {len(self.hidden)}"


# --- Форматирование ---------------------------------------------------------------------------------


def num(value: Decimal | float | int) -> str:
    """12.00 → «12», 6.50 → «6,5», 0.8880 → «0,888»."""
    d = Decimal(str(value)).normalize()
    text = format(d, "f")
    return text.replace(".", ",")


def _slug_num(value: Decimal) -> str:
    return num(value).replace(",", "-")


def _json_num(value: Decimal) -> int | float:
    d = Decimal(str(value)).normalize()
    return int(d) if d == d.to_integral_value() else float(d)


def size_label(rule: LandingRule, values: tuple[Decimal, ...]) -> str:
    """(12,) → «12 мм», (40, 20) → «40х20»."""
    if len(values) == 1:
        return f"{num(values[0])} мм"
    return "х".join(num(v) for v in values)


def size_slug(rule: LandingRule, values: tuple[Decimal, ...]) -> str:
    if len(values) == 1:
        return f"{_slug_num(values[0])}-mm"
    return "x".join(_slug_num(v) for v in values)


def normalize_filters(filters: dict[str, Any]) -> dict[str, str]:
    """Для сравнения: {"diameter_mm": 12} и {"diameter_mm": 12.0} — один фильтр."""
    out = {}
    for key, value in (filters or {}).items():
        try:
            out[key] = num(value)
        except Exception:  # noqa: BLE001 — строковые фильтры (марка стали, ГОСТ)
            out[key] = str(value)
    return out


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _join(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " и " + items[-1] if len(items) > 1 else (items[0] if items else "")


def _units_phrase(products: list[Product]) -> str:
    units = {p.base_unit for p in products} | {pr.unit for p in products for pr in p.prices}
    words = {Unit.METER: "метр", Unit.TON: "тонну", Unit.PIECE: "штуку", Unit.SQUARE_METER: "м²"}
    present = [words[u] for u in (Unit.METER, Unit.SQUARE_METER, Unit.PIECE, Unit.TON) if u in units]
    return "цена за " + _join(present) if present else "цена"


# --- Тексты -----------------------------------------------------------------------------------------


@dataclass
class LandingTexts:
    name: str
    h1: str
    title: str
    description: str
    seo_text: str


def build_texts(rule: LandingRule, values: tuple[Decimal, ...], products: list[Product]) -> LandingTexts:
    """Тексты посадочной из фактов о товарах: марки, ГОСТ, длины, вес метра, метров в тонне.

    Цифры у каждого размера свои, поэтому тексты не повторяют друг друга от страницы к странице.
    {price} подставляется при показе страницы — минимальная цена всегда актуальная.
    """
    s = settings
    name = f"{rule.noun} {size_label(rule, values)}"
    n = len(products)
    availability = "в наличии" if all(p.in_stock for p in products) else "в каталоге"
    grades = sorted({p.steel_grade for p in products if p.steel_grade})
    gosts = sorted({p.gost for p in products if p.gost})
    lengths = sorted({p.length_m for p in products if p.length_m})
    thicknesses = sorted({p.thickness_mm for p in products if p.thickness_mm and "thickness_mm" not in rule.keys})
    weights = sorted({p.weight_per_m_kg for p in products if p.weight_per_m_kg})

    title = f"{name} купить в {s.city_prepositional} {PRICE_TOKEN} — {_units_phrase(products)}"
    if len(title.replace(PRICE_TOKEN, "от 99 999 ₽")) > 75:
        title = f"{name} купить в {s.city_prepositional} {PRICE_TOKEN}"

    facts = []
    if grades:
        facts.append(_join(grades))
    if thicknesses:
        facts.append("стенка " + _join([f"{num(t)} мм" for t in thicknesses]))
    if lengths:
        facts.append("длина " + _join([f"{num(v)} м" for v in lengths]))
    description = (
        f"{name} {PRICE_TOKEN}: {n} {_plural(n, 'позиция', 'позиции', 'позиций')} {availability}"
        + (f" ({'; '.join(facts)})" if facts else "")
        + f". Продаём {rule.piece}, режем в размер, доставка по {s.city_prepositional} и области."
    )

    rows = []
    if grades:
        rows.append(("Марка стали", _join(grades)))
    if thicknesses:
        rows.append(("Толщина стенки", _join([f"{num(t)} мм" for t in thicknesses])))
    if gosts:
        rows.append(("Стандарт", _join(gosts)))
    if lengths:
        rows.append(("Длина", _join([f"{num(v)} м" for v in lengths])))
    if weights:
        if len(weights) == 1:
            per_ton = round(1000 / float(weights[0]))
            rows.append(("Вес 1 метра", f"{num(weights[0])} кг — в тонне около {per_ton} м"))
        else:
            rows.append(("Вес 1 метра", f"от {num(weights[0])} до {num(weights[-1])} кг"))

    parts = [f"<h2>{escape(name)}: характеристики</h2>"]
    if rows:
        items = "".join(f"<li>{escape(k)}: {escape(v)}</li>" for k, v in rows)
        parts.append(f"<ul>{items}</ul>")
    if rule.usage:
        parts.append(f"<p>{escape(rule.usage)}</p>")
    has_ton = any(p.price_for(Unit.TON) for p in products)
    ton = f" При заказе от {num(Decimal(s.ton_price_from_kg) / 1000)} т действует цена за тонну." if has_ton else ""
    parts.append(
        f"<p>Продаём {escape(rule.piece)}, без минимальной партии.{escape(ton)} "
        f"Режем в размер — {escape(format_rub(s.cut_price_kop))} за рез, обрезки отдаём вместе с заказом. "
        f"Доставляем по {escape(s.city_prepositional)} и Московской области на объект.</p>"
    )
    return LandingTexts(name=name, h1=name, title=title, description=description, seo_text="".join(parts))


# --- Генерация --------------------------------------------------------------------------------------


def _common_category(paths: list[str]) -> str:
    """Самый глубокий общий раздел: ["armatura/a500c", "armatura/a1"] → "armatura"."""
    split = [p.split("/") for p in paths]
    common = []
    for parts in zip(*split, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "/".join(common)


async def generate_landings(session: AsyncSession, rules: tuple[LandingRule, ...] = RULES) -> Report:
    report = Report()
    categories = {c.path: c for c in await session.scalars(select(Category))}
    products = list(await session.scalars(select(Product).where(Product.is_active.is_(True))))
    landings = list(await session.scalars(select(FilterLanding)))
    by_path = {item.path: item for item in landings}
    taken = set(categories) | {p.path for p in products}
    seen: set[int] = set()

    for rule in rules:
        root = categories.get(rule.category_path)
        if root is None or not root.is_active:
            continue
        groups: dict[tuple[Decimal, ...], list[Product]] = defaultdict(list)
        for p in products:
            if not p.path.startswith(root.path + "/"):
                continue
            values = tuple(getattr(p, key) for key in rule.keys)
            if all(v is not None for v in values):
                groups[tuple(Decimal(str(v)).normalize() for v in values)].append(p)

        for sort, values in enumerate(sorted(groups), start=1):
            items = sorted(groups[values], key=lambda p: p.path)
            target = _common_category([p.category.path for p in items]) or root.path
            if target not in categories or not target.startswith(root.path):
                target = root.path
            path = f"{target}/{size_slug(rule, values)}"
            filters = {k: _json_num(v) for k, v in zip(rule.keys, values, strict=True)}
            wanted = len(items) >= rule.min_products
            texts = build_texts(rule, values, items)
            landing = by_path.get(path)

            if landing is not None and not landing.is_generated:
                continue  # адрес занят ручной посадочной — она важнее
            if landing is None:
                if not wanted or path in taken:
                    continue
                # Тот же фильтр уже закрыт ручной посадочной в этом разделе — второй страницы не делаем
                if any(
                    not item.is_generated
                    and item.is_indexable
                    and item.path.startswith(root.path + "/")
                    and normalize_filters(item.filters) == normalize_filters(filters)
                    for item in landings
                ):
                    continue
                landing = FilterLanding(
                    category_id=categories[target].id,
                    slug=path.rsplit("/", 1)[1],
                    path=path,
                    is_generated=True,
                )
                session.add(landing)
                landings.append(landing)
                by_path[path] = landing
                report.created.append(path)
            elif landing.is_indexable and not wanted:
                report.hidden.append(path)
            else:
                report.updated.append(path)

            landing.name = texts.name
            landing.h1 = texts.h1
            landing.title = texts.title
            landing.description = texts.description
            landing.seo_text = texts.seo_text
            landing.filters = filters
            landing.sort = sort * 10
            landing.is_indexable = wanted
            if landing.id is not None:
                seen.add(landing.id)

    # Свои посадочные, чей размер пропал из каталога: оставляем адрес, убираем из индекса
    for landing in landings:
        if landing.is_generated and landing.id is not None and landing.id not in seen and landing.is_indexable:
            landing.is_indexable = False
            report.hidden.append(landing.path)

    await session.commit()
    return report


async def main() -> None:
    async with SessionLocal() as session:
        report = await generate_landings(session)
    print(f"Посадочные: {report}")


if __name__ == "__main__":
    asyncio.run(main())
