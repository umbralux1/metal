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
    # Подразделы, которые в эти посадочные не входят: у них своё правило или нет размеров
    # (стеклопластиковая арматура не должна попадать в «Арматуру 8 мм»)
    exclude: tuple[str, ...] = ()

    def covers(self, category_path: str) -> bool:
        """Раздел товара внутри раздела правила и не в исключённом подразделе."""
        if category_path != self.category_path and not category_path.startswith(self.category_path + "/"):
            return False
        inner = category_path[len(self.category_path) :].strip("/").split("/")
        return not any(slug in self.exclude for slug in inner if slug)


RULES: tuple[LandingRule, ...] = (
    LandingRule(
        "armatura",
        ("diameter_mm",),
        "Арматура",
        "от одного прутка",
        "Идёт на ленточный и плитный фундамент, монолитные стены и перекрытия, армирование кладки и отмостки.",
        exclude=("kompozitnaya", "fiksatory", "khomuty"),
    ),
    LandingRule(
        "armatura/kompozitnaya",
        ("diameter_mm",),
        "Арматура стеклопластиковая",
        "от одного прутка",
        "Стеклопластиковая арматура не ржавеет и в несколько раз легче стальной: её берут для фундаментов "
        "небольших построек, отмосток, дорожек и армирования кладки.",
    ),
    LandingRule(
        "truba-profilnaya",
        ("width_mm", "height_mm"),
        "Труба профильная",
        "от одной трубы",
        "Из профильной трубы варят каркасы навесов и теплиц, столбы и лаги забора, ворота, калитки и перила.",
        qualifiers={"kvadratnaya": "квадратная", "pryamougolnaya": "прямоугольная"},
        exclude=("otsinkovannaya",),
    ),
    LandingRule(
        "truba-profilnaya/otsinkovannaya",
        ("width_mm", "height_mm"),
        "Труба профильная оцинкованная",
        "от одной трубы",
        "Оцинкованная профильная труба не требует покраски: её ставят на теплицы, навесы и заборы, "
        "где металл постоянно под дождём.",
    ),
    LandingRule(
        "truba/elektrosvarnaya",
        ("diameter_mm",),
        "Труба электросварная",
        "от одной трубы",
        "Электросварная труба подходит для столбов забора, опор навесов, водопровода и дренажа.",
    ),
    LandingRule(
        "truba/besshovnaya",
        ("diameter_mm",),
        "Труба бесшовная",
        "от одной трубы",
        "Бесшовная труба держит высокое давление: её берут для отопления, гидравлики и ответственных конструкций.",
        qualifiers={
            "goryachedeformirovannaya": "горячедеформированная",
            "kholodnodeformirovannaya": "холоднодеформированная",
        },
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
        ("width_mm",),
        "Полоса стальная",
        "от одной полосы",
        "Полоса идёт на контур заземления, закладные, обвязку и усиление металлоконструкций.",
    ),
    LandingRule(
        "kvadrat",
        ("width_mm",),
        "Квадрат стальной",
        "от одного прутка",
        "Стальной квадрат используют для решёток, ограждений, перил, ворот и кованых элементов.",
    ),
    LandingRule(
        "list/goryachekatanyy",
        ("thickness_mm",),
        "Лист горячекатаный",
        "от одного листа",
        "Горячекатаный лист идёт на ворота, кузова, перекрытие приямков, закладные и раскрой деталей.",
    ),
    LandingRule(
        "list/kholodnokatanyy",
        ("thickness_mm",),
        "Лист холоднокатаный",
        "от одного листа",
        "Холоднокатаный лист с ровной гладкой поверхностью берут для гибки, обшивки, корпусов и под покраску.",
    ),
    LandingRule(
        "list/otsinkovannyy",
        ("thickness_mm",),
        "Лист оцинкованный",
        "от одного листа",
        "Оцинкованный лист идёт на отливы, планки, короба вентиляции, обшивку и кровельные элементы.",
    ),
    LandingRule(
        "svai-vintovye",
        ("diameter_mm",),
        "Сваи винтовые",
        "от одной сваи",
        "Сваи 57–76 мм ставят под забор и лёгкие постройки, 89–108 мм — под дом из бруса и каркасный дом, "
        "133–159 мм — под тяжёлые дома и на слабые грунты.",
        exclude=("ogolovki",),
    ),
)


def rule_for(category_path: str) -> LandingRule | None:
    """Правило для раздела товара: самое точное по адресу раздела
    ("truba-profilnaya/otsinkovannaya" → правило оцинкованной трубы, а не общее профильной)."""
    matches = [rule for rule in RULES if rule.covers(category_path)]
    return max(matches, key=lambda rule: len(rule.category_path), default=None)


def qualifier_for(rule: LandingRule | None, category_path: str) -> str:
    if rule is None:
        return ""
    inner = category_path[len(rule.category_path) :].strip("/").split("/")
    return next((q for slug, q in rule.qualifiers.items() if slug in inner), "")


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
