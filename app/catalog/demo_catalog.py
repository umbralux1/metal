# ruff: noqa: E501 — файл данных: строки с товарами длиннее обычного
"""Демо-каталог: дерево разделов и примеры товаров в каждой группе.

Структура разделов повторяет типовой каталог металлобазы (как у конкурентов из брифа), без групп,
которые по брифу не продаём: кованые изделия, чугун, нержавейка, цветной металл.
Тексты, веса и цены — свои: веса по формулам ГОСТ (для швеллера и балки — табличные значения),
цены УСЛОВНЫЕ, от цены за тонну. Перед запуском их заменит прайс-лист.

sync_demo_catalog() добавляет недостающие разделы и товары и ничего не меняет в уже существующих:
её можно запускать на заполненной базе (на Render — при каждом старте с SEED_DEMO=true).
"""

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Category, Price, Product, Unit
from app.catalog.utils import normalize_search, slugify

D = Decimal
STEEL = 0.00785  # кг на мм² сечения × м длины


# --- Описание товара --------------------------------------------------------------------------------


@dataclass
class Item:
    name: str
    unit: Unit = Unit.PIECE
    prices: dict[Unit, int] = field(default_factory=dict)  # в копейках
    fields: dict[str, Any] = field(default_factory=dict)


def _d(value: float, places: str = "0.001") -> Decimal:
    return D(str(value)).quantize(D(places), rounding=ROUND_HALF_UP)


def _n(value: float) -> str:
    """12 → «12», 1.5 → «1,5» — для названий."""
    text = f"{D(str(value)).normalize():f}"
    return text.replace(".", ",")


def _rub(value: float) -> int:
    """Рубли → копейки."""
    return int(round(value * 100))


def long_item(
    name: str,
    weight_kg_m: float,
    ton_rub: int,
    length_m: float,
    profile: str | None = None,
    **dims: Any,
) -> Item:
    """Длинномер (пруток, труба, уголок): цена за метр от цены за тонну и цена за тонну."""
    fields = {"weight_per_m_kg": _d(weight_kg_m, "0.001"), "length_m": _d(length_m), **dims}
    if profile:
        fields["attrs"] = {"profile": profile}
    meter = math.ceil(ton_rub * float(_d(weight_kg_m, "0.001")) / 1000 * 100) / 100
    return Item(name, Unit.METER, {Unit.METER: _rub(meter), Unit.TON: _rub(ton_rub)}, fields)


def piece(name: str, price_rub: float, extra: dict[Unit, float] | None = None, **fields: Any) -> Item:
    prices = {Unit.PIECE: _rub(price_rub)}
    for unit, value in (extra or {}).items():
        prices[unit] = _rub(value)
    return Item(name, Unit.PIECE, prices, fields)


# --- Сортамент --------------------------------------------------------------------------------------


def rebar(grade: str, gost: str, ton: int, diameters: list[int]) -> list[Item]:
    return [
        long_item(
            f"Арматура {d} мм {grade}",
            0.006165 * d * d,
            ton,
            11.7,
            diameter_mm=D(d),
            steel_grade=grade.replace("А1", "А240"),
            gost=gost,
        )
        for d in diameters
    ]


def profile_pipe(noun: str, ton: int, sizes: list[tuple[float, float, float]], gost: str = "ГОСТ 30245-2003"):
    return [
        long_item(
            f"{noun} {_n(a)}х{_n(b)}х{_n(t)}",
            0.0157 * t * (a + b - 2.86 * t),
            ton,
            6,
            width_mm=_d(a, "0.01"),
            height_mm=_d(b, "0.01"),
            thickness_mm=_d(t, "0.01"),
            steel_grade="Ст3",
            gost=gost,
        )
        for a, b, t in sizes
    ]


def round_pipe(noun: str, ton: int, sizes: list[tuple[float, float]], gost: str, length: float = 6, label=None):
    items = []
    for d, t in sizes:
        name = label(d, t) if label else f"{noun} {_n(d)}х{_n(t)}"
        items.append(
            long_item(
                name,
                0.02466 * t * (d - t),
                ton,
                length,
                profile="pipe",
                diameter_mm=_d(d, "0.01"),
                thickness_mm=_d(t, "0.01"),
                steel_grade="Ст3" if "ВГП" not in name else "Ст2пс",
                gost=gost,
            )
        )
    return items


def angle(noun: str, ton: int, sizes: list[tuple[float, float, float]], gost: str) -> list[Item]:
    return [
        long_item(
            f"{noun} {_n(a)}х{_n(b)}х{_n(t)}",
            (a + b - t) * t * STEEL,
            ton,
            11.7,
            profile="angle",
            width_mm=_d(a, "0.01"),
            height_mm=_d(b, "0.01"),
            thickness_mm=_d(t, "0.01"),
            steel_grade="Ст3",
            gost=gost,
        )
        for a, b, t in sizes
    ]


def by_table(noun: str, ton: int, rows: list[tuple[str, int, float]], gost: str, profile: str) -> list[Item]:
    """Швеллер и балка: номер профиля, высота (мм) и вес метра из сортамента."""
    return [
        long_item(f"{noun} {code}", weight, ton, 12, profile=profile, height_mm=D(h), steel_grade="Ст3", gost=gost)
        for code, h, weight in rows
    ]


def sheets(noun: str, ton: int, rows: list[tuple[float, int, int]], gost: str, grade: str = "Ст3") -> list[Item]:
    """Лист: цена за лист (вес листа × цена тонны) и за тонну."""
    items = []
    for t, w, length in rows:
        sheet_kg = t * 7.85 * (w / 1000) * (length / 1000)
        price = math.ceil(ton * sheet_kg / 1000)
        items.append(
            piece(
                f"{noun} {_n(t)} мм {w}х{length}",
                price,
                {Unit.TON: ton},
                thickness_mm=_d(t, "0.01"),
                steel_grade=grade,
                gost=gost,
                weight_per_piece_kg=D(str(round(sheet_kg, 1))),
                piece_length_m=D(max(w, length)) / 1000,
                attrs={"format": f"{w}×{length}", "sheet_kg": round(sheet_kg, 1)},
            )
        )
    return items


# --- Дерево -----------------------------------------------------------------------------------------


@dataclass
class Node:
    slug: str
    name: str
    items: list[Item] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)


def N(slug: str, name: str, items: list[Item] | None = None, children: list[Node] | None = None) -> Node:
    return Node(slug, name, items or [], children or [])


def _tree() -> list[Node]:
    a500 = "ГОСТ 34028-2016"
    return [
        N(
            "armatura",
            "Арматура",
            children=[
                N("a500c", "Арматура А500С", rebar("А500С", a500, 54000, [8, 10, 12, 14, 16, 20])),
                N("a1", "Арматура гладкая А1", rebar("А1", "ГОСТ 5781-82", 58000, [6, 8, 10, 12])),
                N("a400", "Арматура А400", rebar("А400", "ГОСТ 5781-82", 56000, [10, 12, 16])),
                N(
                    "kompozitnaya",
                    "Арматура стеклопластиковая",
                    [
                        Item(
                            f"Арматура стеклопластиковая {d} мм",
                            Unit.METER,
                            {Unit.METER: _rub(price)},
                            {"diameter_mm": D(d), "gost": "ГОСТ 31938-2012", "attrs": {"profile": "round"}},
                        )
                        for d, price in ((6, 14), (8, 22), (10, 33))
                    ],
                ),
                N(
                    "fiksatory",
                    "Фиксаторы для арматуры",
                    [
                        piece("Фиксатор арматуры звёздочка 20 мм, 100 шт.", 190),
                        piece("Фиксатор арматуры звёздочка 30 мм, 100 шт.", 260),
                        piece("Фиксатор арматуры стульчик 35 мм, 100 шт.", 420),
                    ],
                ),
                N(
                    "khomuty",
                    "Хомуты для арматуры",
                    [
                        piece("Хомут для арматуры 200х200 мм, Ø6", 18),
                        piece("Хомут для арматуры 300х200 мм, Ø6", 22),
                        piece("Хомут для арматуры 400х300 мм, Ø8", 41),
                    ],
                ),
            ],
        ),
        N(
            "truba-profilnaya",
            "Труба профильная",
            children=[
                N(
                    "kvadratnaya",
                    "Труба квадратная",
                    profile_pipe(
                        "Труба профильная",
                        78000,
                        [(20, 20, 2), (25, 25, 2), (40, 40, 2), (40, 40, 3), (60, 60, 3), (80, 80, 3), (100, 100, 4)],
                    ),
                ),
                N(
                    "pryamougolnaya",
                    "Труба прямоугольная",
                    profile_pipe(
                        "Труба профильная",
                        78000,
                        [(40, 20, 1.5), (40, 20, 2), (60, 30, 2), (60, 40, 2), (80, 40, 3), (100, 50, 3)],
                    ),
                ),
                N(
                    "otsinkovannaya",
                    "Труба профильная оцинкованная",
                    profile_pipe("Труба профильная оцинкованная", 98000, [(40, 20, 1.5), (40, 40, 2), (60, 40, 2)]),
                ),
            ],
        ),
        N(
            "truba",
            "Труба круглая",
            children=[
                N(
                    "elektrosvarnaya",
                    "Труба электросварная",
                    round_pipe(
                        "Труба электросварная",
                        76000,
                        [(57, 3), (76, 3), (89, 3.5), (108, 4), (159, 4.5)],
                        "ГОСТ 10704-91",
                    ),
                ),
                N(
                    "vgp",
                    "Труба водогазопроводная (ВГП)",
                    round_pipe(
                        "Труба ВГП",
                        82000,
                        [(21.3, 2.8), (26.8, 2.8), (33.5, 3.2), (42.3, 3.2)],
                        "ГОСТ 3262-75",
                        label=lambda d, t: f"Труба ВГП Ду{ {21.3: 15, 26.8: 20, 33.5: 25, 42.3: 32}[d] }х{_n(t)}",
                    ),
                ),
                N(
                    "otsinkovannaya",
                    "Труба оцинкованная стальная",
                    round_pipe(
                        "Труба ВГП оцинкованная",
                        99000,
                        [(26.8, 2.8), (33.5, 3.2)],
                        "ГОСТ 3262-75",
                        label=lambda d, t: f"Труба ВГП оцинкованная Ду{ {26.8: 20, 33.5: 25}[d] }х{_n(t)}",
                    ),
                ),
                N(
                    "besshovnaya",
                    "Трубы бесшовные",
                    children=[
                        N(
                            "goryachedeformirovannaya",
                            "Трубы горячедеформированные",
                            round_pipe("Труба бесшовная", 112000, [(57, 4), (89, 6), (108, 6)], "ГОСТ 8732-78"),
                        ),
                        N(
                            "kholodnodeformirovannaya",
                            "Трубы холоднодеформированные",
                            round_pipe("Труба бесшовная", 125000, [(25, 2.5), (32, 3), (42, 3)], "ГОСТ 8734-75"),
                        ),
                    ],
                ),
            ],
        ),
        N(
            "list",
            "Листовой прокат",
            children=[
                N(
                    "goryachekatanyy",
                    "Лист горячекатаный",
                    sheets(
                        "Лист горячекатаный",
                        72000,
                        [(2, 1250, 2500), (3, 1250, 2500), (4, 1500, 6000), (5, 1500, 6000), (6, 1500, 6000)],
                        "ГОСТ 19903-2015",
                    ),
                ),
                N(
                    "kholodnokatanyy",
                    "Лист холоднокатаный",
                    sheets(
                        "Лист холоднокатаный",
                        80000,
                        [(0.8, 1250, 2500), (1, 1250, 2500), (1.5, 1250, 2500), (2, 1250, 2500)],
                        "ГОСТ 19904-90",
                        "08пс",
                    ),
                ),
                N(
                    "otsinkovannyy",
                    "Лист оцинкованный",
                    sheets(
                        "Лист оцинкованный",
                        95000,
                        [(0.5, 1250, 2500), (0.7, 1250, 2500), (1, 1250, 2500)],
                        "ГОСТ 14918-2020",
                        "08пс",
                    ),
                ),
                N(
                    "riflenyy-romb",
                    "Лист рифлёный ромб",
                    sheets("Лист рифлёный ромб", 82000, [(3, 1250, 2500), (4, 1500, 6000)], "ГОСТ 8568-77"),
                ),
                N(
                    "riflenyy-chechevitsa",
                    "Лист рифлёный чечевица",
                    sheets("Лист рифлёный чечевица", 82000, [(3, 1250, 2500), (4, 1500, 6000)], "ГОСТ 8568-77"),
                ),
                N(
                    "prosechno-vytyazhnoy",
                    "Лист просечно-вытяжной",
                    [
                        piece("Лист просечно-вытяжной ПВЛ 406 1000х2000", 2950, gost="ТУ 36.26.11-5-89"),
                        piece("Лист просечно-вытяжной ПВЛ 508 1000х2000", 3650, gost="ТУ 36.26.11-5-89"),
                        piece("Лист просечно-вытяжной ПВЛ 510 1000х2000", 4400, gost="ТУ 36.26.11-5-89"),
                    ],
                ),
                N(
                    "alyuminievyy-riflenyy",
                    "Лист алюминиевый рифлёный",
                    [
                        piece(
                            "Лист алюминиевый рифлёный 1,5 мм 1200х3000",
                            6900,
                            thickness_mm=D("1.5"),
                            steel_grade="АМг2",
                        ),
                        piece("Лист алюминиевый рифлёный 2 мм 1200х3000", 8900, thickness_mm=D(2), steel_grade="АМг2"),
                    ],
                ),
            ],
        ),
        N(
            "ugolok",
            "Уголок",
            children=[
                N(
                    "ravnopolochnyy",
                    "Уголок равнополочный",
                    angle(
                        "Уголок",
                        72000,
                        [
                            (25, 25, 3),
                            (32, 32, 4),
                            (40, 40, 4),
                            (50, 50, 4),
                            (50, 50, 5),
                            (63, 63, 5),
                            (75, 75, 6),
                            (100, 100, 8),
                        ],
                        "ГОСТ 8509-93",
                    ),
                ),
                N(
                    "neravnopolochnyy",
                    "Уголок неравнополочный",
                    angle("Уголок", 76000, [(63, 40, 5), (75, 50, 5), (100, 63, 6)], "ГОСТ 8510-86"),
                ),
            ],
        ),
        N(
            "shveller",
            "Швеллер",
            children=[
                N(
                    "goryachekatanyy",
                    "Швеллер горячекатаный",
                    by_table(
                        "Швеллер",
                        76000,
                        [
                            ("10П", 100, 8.59),
                            ("12П", 120, 10.4),
                            ("14П", 140, 12.3),
                            ("16П", 160, 14.2),
                            ("20П", 200, 18.4),
                        ],
                        "ГОСТ 8240-97",
                        "channel",
                    ),
                ),
                N(
                    "gnutyy",
                    "Швеллер гнутый",
                    [
                        long_item(
                            f"Швеллер гнутый {h}х{b}х{_n(t)}",
                            (h + 2 * b - 2 * t) * t * STEEL,
                            80000,
                            6,
                            profile="channel",
                            height_mm=D(h),
                            width_mm=D(b),
                            thickness_mm=_d(t, "0.01"),
                            steel_grade="Ст3",
                            gost="ГОСТ 8278-83",
                        )
                        for h, b, t in ((100, 50, 3), (120, 60, 4), (160, 80, 4))
                    ],
                ),
            ],
        ),
        N(
            "balka",
            "Балка двутавровая",
            children=[
                N(
                    code,
                    title,
                    by_table("Балка двутавровая", 84000, rows, gost, "beam"),
                )
                for code, title, gost, rows in (
                    (
                        "obychnaya",
                        "Двутавр обычный",
                        "ГОСТ 8239-89",
                        [("10", 100, 9.46), ("12", 120, 11.5), ("16", 160, 15.9), ("20", 200, 21.0)],
                    ),
                    (
                        "b1",
                        "Двутавр Б1",
                        "ГОСТ Р 57837-2017",
                        [("10Б1", 100, 8.1), ("12Б1", 117, 8.7), ("16Б1", 157, 12.7), ("20Б1", 200, 21.3)],
                    ),
                    ("b2", "Двутавр Б2", "ГОСТ Р 57837-2017", [("25Б2", 250, 29.6), ("30Б2", 300, 36.6)]),
                    ("b3", "Двутавр Б3", "ГОСТ Р 57837-2017", [("35Б3", 353, 57.0), ("40Б3", 403, 72.0)]),
                    ("k1", "Двутавр К1", "ГОСТ Р 57837-2017", [("20К1", 195, 41.5), ("25К1", 246, 62.6)]),
                    ("k2", "Двутавр К2", "ГОСТ Р 57837-2017", [("20К2", 198, 46.9), ("25К2", 249, 69.2)]),
                    ("sh1", "Двутавр Ш1", "ГОСТ Р 57837-2017", [("20Ш1", 194, 30.6), ("25Ш1", 244, 44.1)]),
                    ("sh2", "Двутавр Ш2", "ГОСТ Р 57837-2017", [("30Ш2", 300, 68.3), ("35Ш2", 342, 82.2)]),
                    ("sh3", "Двутавр Ш3", "ГОСТ Р 57837-2017", [("40Ш3", 400, 124.0), ("50Ш3", 500, 156.0)]),
                    ("sh4", "Двутавр Ш4", "ГОСТ Р 57837-2017", [("60Ш4", 600, 199.0), ("70Ш4", 700, 245.0)]),
                )
            ],
        ),
        N(
            "polosa",
            "Полоса стальная",
            [
                long_item(
                    f"Полоса стальная {w}х{t}",
                    w * t * STEEL,
                    74000,
                    6,
                    profile="plate",
                    width_mm=D(w),
                    thickness_mm=D(t),
                    steel_grade="Ст3",
                    gost="ГОСТ 103-2006",
                )
                for w, t in ((20, 4), (25, 4), (40, 4), (40, 5), (50, 5), (60, 6))
            ],
        ),
        N(
            "kvadrat",
            "Квадрат стальной",
            [
                long_item(
                    f"Квадрат стальной {a} мм",
                    a * a * STEEL,
                    76000,
                    6,
                    profile="square",
                    width_mm=D(a),
                    steel_grade="Ст3",
                    gost="ГОСТ 2591-2006",
                )
                for a in (8, 10, 12, 14, 16)
            ],
        ),
        N(
            "setka",
            "Сетка металлическая",
            children=[
                N(
                    "rabica",
                    "Сетка рабица",
                    [
                        piece("Сетка рабица оцинкованная 50х50х1,6, рулон 1,5х10 м", 1650),
                        piece("Сетка рабица оцинкованная 50х50х2, рулон 1,8х10 м", 2350),
                        piece("Сетка рабица в ПВХ 55х55х2,5, рулон 1,5х10 м", 2900),
                    ],
                ),
                N(
                    "svarnaya-v-kartah",
                    "Сетка сварная в картах",
                    [
                        piece("Сетка сварная 100х100х4, карта 2х3 м", 1290),
                        piece("Сетка сварная 150х150х5, карта 2х3 м", 1480),
                        piece("Сетка сварная 200х200х8, карта 2х3 м", 3350),
                    ],
                ),
                N(
                    "svarnaya-v-rulonah",
                    "Сетка сварная в рулонах",
                    [
                        piece("Сетка сварная оцинкованная 50х50х1,6, рулон 1,5х25 м", 4900),
                        piece("Сетка сварная оцинкованная 25х25х1,4, рулон 1х25 м", 3700),
                    ],
                ),
                N(
                    "svarnaya-pvh",
                    "Сетка сварная ПВХ",
                    [
                        piece("Сетка сварная в ПВХ 50х50х1,8, рулон 1,5х25 м", 6200),
                        piece("Сетка сварная в ПВХ 100х50х2,2, рулон 1,8х25 м", 7900),
                    ],
                ),
                N(
                    "shtukaturnaya",
                    "Сетка штукатурная плетёная",
                    [
                        piece("Сетка штукатурная плетёная 10х10х0,6, рулон 1х10 м", 890),
                        piece("Сетка штукатурная плетёная 20х20х0,8, рулон 1х10 м", 990),
                    ],
                ),
                N(
                    "kladochnaya",
                    "Сетка кладочная",
                    [
                        piece("Сетка кладочная 50х50х3, карта 0,5х2 м", 120),
                        piece("Сетка кладочная 100х100х4, карта 0,5х2 м", 150),
                    ],
                ),
            ],
        ),
        N(
            "provoloka",
            "Проволока вязальная",
            [
                piece("Проволока вязальная 1,2 мм, моток 2 кг", 390, diameter_mm=D("1.2"), attrs={"profile": "round"}),
                piece("Проволока вязальная 1,6 мм, моток 5 кг", 890, diameter_mm=D("1.6"), attrs={"profile": "round"}),
                piece(
                    "Проволока вязальная оцинкованная 1,2 мм, моток 2 кг",
                    520,
                    diameter_mm=D("1.2"),
                    attrs={"profile": "round"},
                ),
            ],
        ),
        N(
            "zaglushki",
            "Заглушки для профильных труб",
            children=[
                N(
                    "metallicheskie",
                    "Заглушки металлические",
                    [
                        piece("Заглушка металлическая 20х20", 12),
                        piece("Заглушка металлическая 40х40", 19),
                        piece("Заглушка металлическая 60х40", 24),
                    ],
                ),
                N(
                    "plastikovye",
                    "Заглушки пластиковые",
                    [
                        piece("Заглушка пластиковая 20х20", 5),
                        piece("Заглушка пластиковая 40х20", 6),
                        piece("Заглушка пластиковая 60х60", 11),
                    ],
                ),
            ],
        ),
        N(
            "profnastil",
            "Профнастил",
            children=[
                N(
                    "okrashennyy",
                    "Профнастил окрашенный",
                    [
                        piece(
                            f"Профнастил {mark} RAL {ral} {_n(t)} мм, лист 2 м",
                            m2 * 2.3,
                            {Unit.SQUARE_METER: m2},
                            thickness_mm=_d(t, "0.01"),
                            attrs={"mark": mark, "ral": ral},
                        )
                        for mark, ral, t, m2 in (
                            ("С8", "8017", 0.45, 520),
                            ("С20", "6005", 0.45, 560),
                            ("С21", "3005", 0.5, 610),
                            ("НС35", "5005", 0.5, 640),
                            ("НС44", "7024", 0.5, 670),
                        )
                    ],
                ),
                N(
                    "otsinkovannyy",
                    "Профнастил оцинкованный",
                    [
                        piece(
                            f"Профнастил {mark} оцинкованный {_n(t)} мм, лист 2 м",
                            m2 * 2.3,
                            {Unit.SQUARE_METER: m2},
                            thickness_mm=_d(t, "0.01"),
                            attrs={"mark": mark},
                        )
                        for mark, t, m2 in (
                            ("С8", 0.4, 390),
                            ("С20", 0.45, 430),
                            ("С21", 0.5, 480),
                            ("НС44", 0.5, 520),
                            ("Н60", 0.7, 760),
                            ("Н75", 0.7, 820),
                            ("Н114", 0.8, 1090),
                        )
                    ],
                ),
            ],
        ),
        N(
            "shtaketnik",
            "Штакетник металлический",
            children=[
                N(
                    slug,
                    title,
                    [
                        piece(f"Штакетник {short} RAL 8017 односторонний, 1,5 м", one),
                        piece(f"Штакетник {short} RAL 8017 двусторонний, 1,5 м", two),
                    ],
                )
                for slug, title, short, one, two in (
                    ("p-obraznyy", "Штакетник П-образный", "П-образный 120 мм", 145, 175),
                    ("m-obraznyy", "Штакетник М-образный", "М-образный 115 мм", 150, 180),
                    ("polukruglyy", "Штакетник полукруглый", "полукруглый 128 мм", 165, 195),
                )
            ],
        ),
        N(
            "zabory",
            "Заборы",
            children=[
                N(
                    "stolby",
                    "Столбы для забора",
                    [
                        piece("Столб для забора 60х60х2, 2,5 м, с заглушкой", 1090),
                        piece("Столб для забора 60х60х2, 3 м, с заглушкой", 1290),
                        piece("Столб для забора 80х80х3, 3 м, с заглушкой", 2350),
                    ],
                ),
                N(
                    "lagi",
                    "Лаги для забора",
                    [
                        piece("Лага для забора 40х20х1,5, 3 м", 390),
                        piece("Лага для забора 40х20х2, 6 м", 960),
                    ],
                ),
                N(
                    "komplektuyushchie",
                    "Комплектующие для забора",
                    [
                        piece("Кронштейн для крепления лаги к столбу", 45),
                        piece("Колпак на столб 60х60, оцинкованный", 120),
                        piece("Петля для калитки приварная 20 мм", 95),
                    ],
                ),
            ],
        ),
        N(
            "krepezh",
            "Крепёж",
            children=[
                N(
                    "metricheskiy",
                    "Метрический крепёж",
                    children=[
                        N(
                            "gayki",
                            "Гайки",
                            [piece("Гайка М10 DIN 934, 1 кг", 390), piece("Гайка М12 DIN 934, 1 кг", 380)],
                        ),
                        N(
                            "shayby",
                            "Шайбы",
                            [piece("Шайба М10 DIN 125, 1 кг", 360), piece("Шайба М12 DIN 125, 1 кг", 350)],
                        ),
                        N(
                            "shpilki",
                            "Шпильки",
                            [
                                piece("Шпилька резьбовая М10х1000 DIN 975", 95),
                                piece("Шпилька резьбовая М12х1000 DIN 975", 130),
                            ],
                        ),
                        N(
                            "bolty",
                            "Болты",
                            [piece("Болт М10х50 DIN 933, 1 кг", 420), piece("Болт М12х60 DIN 933, 1 кг", 410)],
                        ),
                    ],
                ),
                N(
                    "santekhnicheskiy",
                    "Сантехнический крепёж",
                    children=[
                        N(
                            "khomuty",
                            "Хомуты сантехнические",
                            [
                                piece('Хомут сантехнический 1" (32–35 мм) с резиной', 45),
                                piece('Хомут сантехнический 2" (59–63 мм) с резиной', 62),
                            ],
                        ),
                        N(
                            "shpilki",
                            "Шпильки сантехнические",
                            [piece("Шпилька сантехническая М8х100", 14), piece("Шпилька сантехническая М10х120", 19)],
                        ),
                    ],
                ),
                N(
                    "gvozdi",
                    "Гвозди строительные",
                    [piece("Гвозди строительные 100 мм, 5 кг", 690), piece("Гвозди строительные 70 мм, 5 кг", 720)],
                ),
                N(
                    "samorezy",
                    "Саморезы",
                    children=[
                        N(
                            "gipsokarton",
                            "Саморезы для гипсокартона",
                            [
                                piece("Саморез по ГКЛ 3,5х35, 1000 шт.", 540),
                                piece("Саморез по ГКЛ 3,5х25, 1000 шт.", 430),
                            ],
                        ),
                        N(
                            "po-metallu",
                            "Саморезы по металлу",
                            [
                                piece("Саморез с прессшайбой 4,2х16, 1000 шт.", 690),
                                piece("Саморез с буром 4,2х16, 1000 шт.", 890),
                            ],
                        ),
                        N(
                            "krovelnye",
                            "Саморезы кровельные",
                            [
                                piece("Саморез кровельный 4,8х35 RAL 8017, 250 шт.", 790),
                                piece("Саморез кровельный 5,5х19 оцинкованный, 250 шт.", 620),
                            ],
                        ),
                    ],
                ),
                N(
                    "ankery",
                    "Анкеры",
                    [piece("Анкерный болт с гайкой 10х100", 24), piece("Анкерный болт с гайкой 12х129", 39)],
                ),
                N(
                    "dyubeli",
                    "Дюбели",
                    [piece("Дюбель распорный 6х40, 100 шт.", 190), piece("Дюбель распорный 8х60, 100 шт.", 290)],
                ),
            ],
        ),
        N(
            "fitingi",
            "Фитинги стальные",
            children=[
                N("bochata", "Бочата", [piece("Бочонок стальной Ду20", 39), piece("Бочонок стальной Ду25", 55)]),
                N("mufty", "Муфты", [piece("Муфта стальная Ду20", 45), piece("Муфта стальная Ду25", 62)]),
                N("otvody", "Отводы", [piece("Отвод 90° 57х3", 140), piece("Отвод 90° 89х3,5", 290)]),
                N("rezba", "Резьба", [piece("Резьба стальная Ду20", 32), piece("Резьба стальная Ду25", 44)]),
                N(
                    "sgony",
                    "Сгоны",
                    [piece("Сгон стальной Ду20 в сборе", 160), piece("Сгон стальной Ду25 в сборе", 210)],
                ),
                N(
                    "flantsy",
                    "Фланцы и переходы",
                    [piece("Фланец плоский Ду50 Ру16", 490), piece("Переход стальной 57х45", 120)],
                ),
            ],
        ),
        N(
            "svai-vintovye",
            "Винтовые сваи",
            [
                piece(
                    f"Свая винтовая {d}х{_n(t)}, {length} мм",
                    price,
                    diameter_mm=D(d),
                    thickness_mm=_d(t, "0.01"),
                    steel_grade="Ст3",
                    piece_length_m=D(length) / 1000,  # вес сваи неизвестен — не выдумываем
                    attrs={"profile": "pile", "length_mm": length},
                )
                for d, t, length, price in (
                    (57, 3.5, 2000, 1890),
                    (57, 3.5, 2500, 2190),
                    (76, 3.5, 2500, 2690),
                    (76, 3.5, 3000, 3090),
                    (89, 4, 2500, 3390),
                    (89, 4, 3000, 3890),
                    (108, 4, 3000, 4990),
                    (108, 4, 3500, 5590),
                    (133, 4.5, 3000, 6990),
                    (159, 5, 3000, 8990),
                )
            ],
            children=[
                N(
                    "ogolovki",
                    "Оголовки для свай",
                    [
                        piece("Оголовок для сваи 57 мм, 150х150", 290),
                        piece("Оголовок для сваи 89 мм, 200х200", 390),
                        piece("Оголовок для сваи 108 мм, 250х250", 490),
                    ],
                ),
            ],
        ),
        N(
            "petli",
            "Петли",
            [
                piece("Петля гаражная 20 мм", 95),
                piece("Петля гаражная 30 мм", 160),
                piece("Петля воротная с подшипником 30 мм", 420),
            ],
        ),
        N(
            "stroymaterialy",
            "Стройматериалы",
            children=[
                N(
                    "bloki",
                    "Блоки строительные",
                    children=[
                        N(
                            "gazobetonnye",
                            "Блоки газобетонные",
                            [
                                piece("Газобетонный блок D500 600х300х200", 230),
                                piece("Газобетонный блок D500 600х250х100", 105),
                            ],
                        ),
                        N(
                            "pazogrebnevye",
                            "Пазогребневые плиты",
                            [piece("Плита пазогребневая полнотелая 667х500х80", 290)],
                        ),
                        N("penobloki", "Пеноблоки", [piece("Пеноблок D600 600х300х200", 210)]),
                    ],
                ),
                N(
                    "diski",
                    "Диски отрезные",
                    [
                        piece("Круг отрезной по металлу 125х1,2х22", 45),
                        piece("Круг отрезной по металлу 230х2,5х22", 120),
                    ],
                ),
                N(
                    "izolyatsiya",
                    "Изоляционные материалы",
                    children=[
                        N(
                            "gidroizolyatsiya",
                            "Гидроизоляция",
                            [
                                piece("Пароизоляционная плёнка, рулон 70 м²", 1290),
                                piece("Гидроизоляционная мембрана, рулон 75 м²", 2390),
                            ],
                        ),
                        N(
                            "uteplitel",
                            "Утеплитель",
                            [
                                piece("Утеплитель минеральная вата 50 мм, упаковка 6 м²", 990),
                                piece("Утеплитель минеральная вата 100 мм, упаковка 3 м²", 990),
                            ],
                        ),
                    ],
                ),
                N(
                    "fanera-osb",
                    "Фанера и OSB",
                    [
                        piece("Плита OSB-3 9 мм 2500х1250", 890),
                        piece("Плита OSB-3 12 мм 2500х1250", 1090),
                        piece("Фанера ФК 10 мм 1525х1525", 1190),
                    ],
                ),
                N(
                    "profil-gkl",
                    "Профиль для гипсокартона",
                    [piece("Профиль потолочный ПП 60х27, 3 м", 210), piece("Профиль направляющий ПН 28х27, 3 м", 150)],
                ),
                N(
                    "elektrody",
                    "Электроды",
                    [piece("Электроды МР-3 3 мм, 5 кг", 1290), piece("Электроды МР-3 4 мм, 5 кг", 1250)],
                ),
                N(
                    "smesi",
                    "Сухие смеси и грунтовки",
                    children=[
                        N(slug, title, [piece(name, price)])
                        for slug, title, name, price in (
                            ("vyazhushchie", "Вяжущие и наполнители", "Известь гашёная, 10 кг", 290),
                            ("plitochnyy-kley", "Плиточный клей", "Клей плиточный усиленный, 25 кг", 490),
                            ("gruntovka", "Грунтовка", "Грунтовка глубокого проникновения, 10 л", 690),
                            ("peskobeton", "Пескобетон", "Пескобетон М300, 40 кг", 290),
                            ("zatirki", "Затирки для плитки", "Затирка для плитки серая, 2 кг", 230),
                            ("kleevye", "Клеевые составы", "Клей для газобетона, 25 кг", 420),
                            ("dlya-pola", "Смеси для пола", "Наливной пол, 25 кг", 590),
                            ("obshchestroitelnye", "Смеси общестроительные", "Смесь кладочная М150, 40 кг", 310),
                            ("tsement", "Цемент", "Цемент М500, 50 кг", 650),
                            ("shpaklevka", "Шпаклёвка", "Шпаклёвка финишная полимерная, 20 кг", 890),
                            ("shtukaturka", "Штукатурка", "Штукатурка гипсовая, 30 кг", 520),
                            ("ochistiteli", "Очистители строительные", "Очиститель цементного налёта, 1 л", 390),
                            ("keramzit", "Керамзит", "Керамзит фракция 10–20 мм, 50 л", 190),
                        )
                    ],
                ),
            ],
        ),
    ]


# --- Синхронизация с базой --------------------------------------------------------------------------


def _walk(nodes: list[Node], parent: str = "") -> Iterator[tuple[str, Node, int]]:
    for index, node in enumerate(nodes, start=1):
        path = f"{parent}/{node.slug}" if parent else node.slug
        yield path, node, index * 10
        yield from _walk(node.children, path)


@dataclass
class SyncReport:
    categories: int = 0
    products: int = 0
    product_ids: set[int] = field(default_factory=set)


async def sync_demo_catalog(
    session: AsyncSession, tree: Callable[[], list[Node]] = _tree, commit: bool = True
) -> SyncReport:
    """Добавляет недостающие разделы и товары. Существующие не трогает (сравнение по адресу раздела
    и по названию товара внутри раздела)."""
    report = SyncReport()
    categories = {c.path: c for c in await session.scalars(select(Category))}
    existing = {(p.category_id, p.name) for p in await session.scalars(select(Product))}
    new_products: list[Product] = []

    for path, node, sort in _walk(tree()):
        category = categories.get(path)
        if category is None:
            parent_path = path.rsplit("/", 1)[0] if "/" in path else None
            category = Category(
                slug=node.slug,
                path=path,
                name=node.name,
                sort=sort,
                parent=categories.get(parent_path) if parent_path else None,
            )
            session.add(category)
            await session.flush()
            categories[path] = category
            report.categories += 1
        for item in node.items:
            if (category.id, item.name) in existing:
                continue
            fields = dict(item.fields)
            text = " ".join([item.name, fields.get("steel_grade") or "", fields.get("gost") or ""])
            product = Product(
                category=category,
                slug=slugify(item.name),
                path=f"{path}/{slugify(item.name)}",
                name=item.name,
                base_unit=item.unit,
                search_text=normalize_search(text),
                prices=[Price(unit=u, amount_kop=a) for u, a in item.prices.items()],
                **fields,
            )
            session.add(product)
            new_products.append(product)
            existing.add((category.id, item.name))

    await session.flush()
    report.products = len(new_products)
    report.product_ids = {p.id for p in new_products}
    if commit:
        await session.commit()
    return report
