"""Генератор посадочных «по размеру» из номенклатуры каталога по правилам из landing_rules.py.

Запуск: python -m app.catalog.landings (на хостинге — сам при каждом старте, в админке — «Обновить из каталога»).

- Создаёт посадочные под размеры, которые есть в товарах, с title, description, H1 и текстом из данных товаров.
- Обновляет свои (is_generated) посадочные: тексты, фильтр, «в индексе».
- Размер пропал или товаров стало меньше порога — страница не удаляется, а получает noindex (адрес не ломается).
- Ручные посадочные не трогает. Посадочная, которую поправили в админке, становится ручной.
- Ведёт адреса товаров: товар размера лежит внутри его посадочной (…/20x20/20x20x2/), старые адреса — 301.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.landing_rules import RULES, LandingRule, display_name, product_slug, qualifier_for, rule_for
from app.catalog.models import Category, FilterLanding, Product, Unit
from app.catalog.repository import PRODUCT_CARD
from app.catalog.utils import slugify
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.numbers import format_decimal
from app.core.templating import format_rub
from app.seo.meta import PRICE_TOKEN


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)  # товары, сменившие адрес

    def __str__(self) -> str:
        return (
            f"создано {len(self.created)}, обновлено {len(self.updated)}, скрыто из индекса {len(self.hidden)}, "
            f"товаров с новым адресом {len(self.moved)}"
        )


# --- Форматирование ---------------------------------------------------------------------------------


def _slug_num(value: Decimal) -> str:
    return format_decimal(value).replace(",", "-")


def _json_num(value: Decimal) -> int | float:
    d = Decimal(str(value)).normalize()
    return int(d) if d == d.to_integral_value() else float(d)


def size_label(rule: LandingRule, values: tuple[Decimal, ...]) -> str:
    """(12,) → «12 мм», (40, 20) → «40х20»."""
    if len(values) == 1:
        return f"{format_decimal(values[0])} мм"
    return "х".join(format_decimal(v) for v in values)


def size_slug(rule: LandingRule, values: tuple[Decimal, ...]) -> str:
    if len(values) == 1:
        return f"{_slug_num(values[0])}-mm"
    return "x".join(_slug_num(v) for v in values)


def normalize_filters(filters: dict[str, Any]) -> dict[str, str]:
    """Для сравнения: {"diameter_mm": 12} и {"diameter_mm": 12.0} — один фильтр."""
    out = {}
    for key, value in (filters or {}).items():
        try:
            out[key] = format_decimal(value)
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


def build_texts(
    rule: LandingRule, values: tuple[Decimal, ...], products: list[Product], qualifier: str = ""
) -> LandingTexts:
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

    # В title и description — с уточнением подраздела: «Труба профильная квадратная 40х40»
    shown = f"{rule.noun} {qualifier} {size_label(rule, values)}" if qualifier else name
    title = f"{shown} купить в {s.city_prepositional} {PRICE_TOKEN} — {_units_phrase(products)}"
    if len(title.replace(PRICE_TOKEN, "от 99 999 ₽")) > 75:
        title = f"{shown} купить в {s.city_prepositional} {PRICE_TOKEN}"

    facts = []
    if grades:
        facts.append(_join(grades))
    if thicknesses:
        facts.append("стенка " + _join([f"{format_decimal(t)} мм" for t in thicknesses]))
    if lengths:
        facts.append("длина " + _join([f"{format_decimal(v)} м" for v in lengths]))
    description = (
        f"{shown} {PRICE_TOKEN}: {n} {_plural(n, 'позиция', 'позиции', 'позиций')} {availability}"
        + (f" ({'; '.join(facts)})" if facts else "")
        + f". Продаём {rule.piece}, режем в размер, доставка по {s.city_prepositional} и области."
    )

    rows = []
    if grades:
        rows.append(("Марка стали", _join(grades)))
    if thicknesses:
        rows.append(("Толщина стенки", _join([f"{format_decimal(t)} мм" for t in thicknesses])))
    if gosts:
        rows.append(("Стандарт", _join(gosts)))
    if lengths:
        rows.append(("Длина", _join([f"{format_decimal(v)} м" for v in lengths])))
    if weights:
        if len(weights) == 1:
            per_ton = round(1000 / float(weights[0]))
            rows.append(("Вес 1 метра", f"{format_decimal(weights[0])} кг — в тонне около {per_ton} м"))
        else:
            rows.append(("Вес 1 метра", f"от {format_decimal(weights[0])} до {format_decimal(weights[-1])} кг"))

    parts = [f"<h2>{escape(name)}: характеристики</h2>"]
    if rows:
        items = "".join(f"<li>{escape(k)}: {escape(v)}</li>" for k, v in rows)
        parts.append(f"<ul>{items}</ul>")
    if rule.usage:
        parts.append(f"<p>{escape(rule.usage)}</p>")
    has_ton = any(p.price_for(Unit.TON) for p in products)
    ton = (
        f" При заказе от {format_decimal(Decimal(s.ton_price_from_kg) / 1000)} т действует цена за тонну."
        if has_ton
        else ""
    )
    parts.append(
        f"<p>Продаём {escape(rule.piece)}, без минимальной партии.{escape(ton)} "
        f"Режем в размер — {escape(format_rub(s.cut_price_kop))} за рез, обрезки отдаём вместе с заказом. "
        f"Доставляем по {escape(s.city_prepositional)} и Московской области на объект.</p>"
    )
    return LandingTexts(name=name, h1=name, title=title, description=description, seo_text="".join(parts))


# --- Текст карточки товара ------------------------------------------------------------------------


def product_seo_text(product: Product) -> str:
    """Абзацы для карточки из данных товара: вес, метров в тонне, вес и цена штуки, где применяют.

    Показывается, если в админке у товара не задан свой SEO-текст.
    """
    s = settings
    rule = rule_for(product.category.path) if product.category else None
    shown = display_name(product.name, product.category.path) if product.category else product.name
    sentences = []
    if product.weight_per_m_kg:
        w = Decimal(str(product.weight_per_m_kg))
        per_ton = round(1000 / float(w))
        sentences.append(f"Вес 1 метра — {format_decimal(w)} кг, в тонне около {per_ton} м.")
        if product.length_m:
            piece_kg = (w * Decimal(str(product.length_m))).quantize(Decimal("0.01"))
            sentences.append(
                f"Одна штука длиной {format_decimal(product.length_m)} м весит {format_decimal(piece_kg)} кг."
            )
    facts = [
        x
        for x in (
            product.steel_grade and f"марка — {product.steel_grade}",
            product.gost and f"стандарт — {product.gost}",
        )
        if x
    ]
    if facts:
        line = ", ".join(facts)
        sentences.append(line[:1].upper() + line[1:] + ".")
    meter = product.price_for(Unit.METER)
    if meter and product.length_m:
        piece_kop = round(meter.amount_kop * float(product.length_m))
        sentences.append(f"Цена за штуку {format_decimal(product.length_m)} м — {format_rub(piece_kop)}.")
    parts = [f"<h2>{escape(shown)}</h2>"]
    if sentences:
        parts.append(f"<p>{escape(' '.join(sentences))}</p>")
    if rule and rule.usage:
        parts.append(f"<p>{escape(rule.usage)}</p>")
    piece = rule.piece if rule else "от одной штуки"
    parts.append(
        f"<p>Продаём {escape(piece)}, режем в размер — {escape(format_rub(s.cut_price_kop))} за рез. "
        f"Доставляем по {escape(s.city_prepositional)} и Московской области на объект.</p>"
    )
    return "".join(parts)


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


def _in_subtree(category_path: str, root: str) -> bool:
    return category_path == root or category_path.startswith(root + "/")


async def generate_landings(
    session: AsyncSession, rules: tuple[LandingRule, ...] = RULES, fresh_ids: set[int] | None = None
) -> Report:
    """Посадочные под размеры и адреса товаров.

    Товар размера лежит внутри посадочной: /catalog/truba-profilnaya/kvadratnaya/20x20/20x20x2/.
    Остальные товары — внутри своего раздела. Сменился адрес — ставится 301 со старого
    (кроме товаров из fresh_ids: их только что создали, старый адрес нигде не успел появиться).
    """
    report = Report()
    fresh_ids = fresh_ids or set()
    categories = {c.path: c for c in await session.scalars(select(Category))}
    products = list(await session.scalars(select(Product).where(Product.is_active.is_(True)).options(*PRODUCT_CARD)))
    landings = list(await session.scalars(select(FilterLanding)))
    by_path = {item.path: item for item in landings}
    taken = set(categories) | {p.path for p in products}
    seen: set[int] = set()
    parent_of: dict[int, str] = {}  # товар → адрес посадочной, внутри которой он лежит

    for rule in rules:
        root = categories.get(rule.category_path)
        if root is None or not root.is_active:
            continue
        groups: dict[tuple[Decimal, ...], list[Product]] = defaultdict(list)
        for p in products:
            if not p.category or not rule.covers(p.category.path):
                continue
            values = tuple(getattr(p, key) for key in rule.keys)
            if all(v is not None for v in values):
                groups[tuple(Decimal(str(v)).normalize() for v in values)].append(p)

        for sort, values in enumerate(sorted(groups), start=1):
            items = sorted(groups[values], key=lambda p: p.name)
            target = _common_category([p.category.path for p in items]) or root.path
            if target not in categories or not _in_subtree(target, root.path):
                target = root.path
            path = f"{target}/{size_slug(rule, values)}"
            filters = {k: _json_num(v) for k, v in zip(rule.keys, values, strict=True)}
            wanted = len(items) >= rule.min_products
            landing = by_path.get(path)
            # Ручная посадочная с тем же фильтром в этом разделе важнее — товары кладём в неё
            manual = next(
                (
                    item
                    for item in landings
                    if not item.is_generated
                    and item.path.startswith(root.path + "/")
                    and normalize_filters(item.filters) == normalize_filters(filters)
                ),
                None,
            )

            if landing is not None and not landing.is_generated:
                parent = landing if normalize_filters(landing.filters) == normalize_filters(filters) else manual
            elif manual is not None:
                parent = manual
                if landing is not None and landing.is_indexable:  # дубль ручной — убираем из индекса
                    landing.is_indexable = False
                    report.hidden.append(landing.path)
            else:
                if landing is None:
                    if path in taken:
                        continue
                    # Посадочная создаётся и для одного товара — как раздел-родитель для его адреса,
                    # но в индекс идёт только с MIN_PRODUCTS товарами (иначе дублирует карточку)
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
                texts = build_texts(rule, values, items, qualifier_for(rule, target))
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
                parent = landing

            if parent is not None:
                for p in items:
                    parent_of[p.id] = parent.path

    # Свои посадочные, чей размер пропал из каталога: оставляем адрес, убираем из индекса
    for landing in landings:
        if landing.is_generated and landing.id is not None and landing.id not in seen and landing.is_indexable:
            landing.is_indexable = False
            report.hidden.append(landing.path)

    await session.flush()
    await _sync_product_paths(session, products, parent_of, taken, fresh_ids, report)
    await session.commit()
    return report


async def _sync_product_paths(
    session: AsyncSession,
    products: list[Product],
    parent_of: dict[int, str],
    taken: set[str],
    fresh_ids: set[int],
    report: Report,
) -> None:
    from app.catalog.paths import add_redirect

    for p in sorted(products, key=lambda item: item.path):
        if not p.category:
            continue
        # Slug, собранный из названия (старый длинный или новый короткий), приводим к короткому;
        # slug, заданный в админке руками, не трогаем
        short = product_slug(p.name, p.category.path)
        if p.slug in (slugify(p.name), short):
            p.slug = short
        parent = parent_of.get(p.id, p.category.path)
        new_path = f"{parent}/{p.slug}"
        if new_path == p.path or new_path in taken:
            continue
        old_path = p.path
        taken.discard(old_path)
        taken.add(new_path)
        p.path = new_path
        await session.flush()
        if p.id not in fresh_ids:
            await add_redirect(session, old_path, new_path)
        report.moved.append(new_path)


async def main() -> None:
    async with SessionLocal() as session:
        report = await generate_landings(session)
    await engine.dispose()
    print(f"Посадочные: {report}")


if __name__ == "__main__":
    asyncio.run(main())
