"""Семантика посадочных «по размеру»: какие разделы и по каким размерам получают отдельные страницы.

Правило срабатывает, только если раздел с таким адресом есть в каталоге. Страница создаётся под каждое
сочетание размеров, которое реально есть в товарах раздела (вместе с подразделами), и кладётся в самый
глубокий раздел, где лежат все её товары: «Арматура 12 мм» (А500С + А1) → /catalog/armatura/12-mm/,
«Труба профильная 40х40» (только квадратные) → /catalog/truba-profilnaya/kvadratnaya/40x40/.

Размер с толщиной стенки («40х20х2», «50х50х5») обычно и есть один товар — его закрывает страница товара,
поэтому посадочная собирается по размеру без толщины и объединяет все толщины.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.catalog.utils import slugify

# Сколько товаров должно попасть на посадочную, чтобы её открыть для поиска. Страница с одним товаром
# дублирует страницу этого товара и конкурирует с ней в выдаче.
MIN_PRODUCTS = 2


@dataclass(frozen=True)
class LandingRule:
    category_path: str  # адрес раздела без /catalog/: "armatura", "truba-profilnaya"
    keys: tuple[str, ...]  # поля товара, из которых складывается размер (см. FILTERABLE_COLUMNS)
    noun: str  # начало названия: «Арматура» → «Арматура 12 мм»
    piece: str  # «от одного прутка», «от одной трубы» — для текста
    usage: str = ""  # где применяют — абзац текста и запросы «под задачу»
    min_products: int = MIN_PRODUCTS
    # Уточнение по подразделу для title и description: {"kvadratnaya": "квадратная"} →
    # «Труба профильная квадратная 20х20х2 купить…» — так ищут не реже, чем «труба профильная 20х20».
    qualifiers: Mapping[str, str] = field(default_factory=dict)


RULES: tuple[LandingRule, ...] = (
    LandingRule(
        "armatura",
        ("diameter_mm",),
        "Арматура",
        "от одного прутка",
        "Идёт на ленточный и плитный фундамент, монолитные стены и перекрытия, армирование кладки и отмостки.",
    ),
    LandingRule(
        "truba-profilnaya",
        ("width_mm", "height_mm"),
        "Труба профильная",
        "от одной трубы",
        "Из профильной трубы варят каркасы навесов и теплиц, столбы и лаги забора, ворота, калитки и перила.",
        qualifiers={"kvadratnaya": "квадратная", "pryamougolnaya": "прямоугольная", "otsinkovannaya": "оцинкованная"},
    ),
    LandingRule(
        "ugolok",
        ("width_mm", "height_mm"),
        "Уголок",
        "от одного уголка",
        "Уголок берут для обвязки и усиления каркасов, стеллажей, закладных, рам ворот и опор навесов.",
        qualifiers={"ravnopolochnyy": "равнополочный", "neravnopolochnyy": "неравнополочный"},
    ),
    LandingRule(
        "polosa",
        ("width_mm", "thickness_mm"),
        "Полоса стальная",
        "от одной полосы",
        "Полоса идёт на контур заземления, закладные, обвязку и усиление металлоконструкций.",
    ),
    LandingRule(
        "list",
        ("thickness_mm",),
        "Лист",
        "от одного листа",
        "Лист используют для обшивки, ворот, кузовов, перекрытия приямков и изготовления закладных.",
    ),
    LandingRule(
        "truba-elektrosvarnaya",
        ("diameter_mm",),
        "Труба электросварная",
        "от одной трубы",
        "Электросварная труба подходит для столбов забора, опор навесов, водопровода и дренажа.",
    ),
    LandingRule(
        "svai-vintovye",
        ("diameter_mm",),
        "Сваи винтовые",
        "от одной сваи",
        "Сваи 57–76 мм ставят под забор и лёгкие постройки, 89–108 мм — под дом из бруса и каркасный дом, "
        "133–159 мм — под тяжёлые дома и на слабые грунты.",
    ),
)


def rule_for(category_path: str) -> LandingRule | None:
    """Правило для раздела товара: по корню адреса раздела ("truba-profilnaya/kvadratnaya" → труба)."""
    root = category_path.split("/")[0]
    return next((rule for rule in RULES if rule.category_path == root), None)


def qualifier_for(rule: LandingRule | None, category_path: str) -> str:
    if rule is None:
        return ""
    return next((q for slug, q in rule.qualifiers.items() if slug in category_path.split("/")[1:]), "")


def display_name(name: str, category_path: str) -> str:
    """«Труба профильная 20х20х2» в разделе квадратных → «Труба профильная квадратная 20х20х2»."""
    rule = rule_for(category_path)
    qualifier = qualifier_for(rule, category_path)
    if rule and qualifier and name.startswith(rule.noun + " ") and qualifier not in name.lower():
        return f"{rule.noun} {qualifier} {name[len(rule.noun) + 1 :]}"
    return name


def product_slug(name: str, category_path: str) -> str:
    """Короткий slug товара внутри посадочной: «Труба профильная 20х20х2» → «20x20x2»,
    «Арматура 12 мм А500С» → «12-mm-a500s». Без правила — slug из полного названия."""
    full = slugify(name)
    rule = rule_for(category_path)
    prefix = slugify(rule.noun) + "-" if rule else ""
    return full[len(prefix) :] if prefix and full.startswith(prefix) and len(full) > len(prefix) else full
