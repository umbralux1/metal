"""Админка каталога: разделы, товары с ценами в рублях, цены, посадочные.

Адреса (slug, path) и поисковый текст считаются сами при сохранении. Старый адрес и цены из формы передаются
из `on_model_change` в `after_model_change` через `request.state` — один запрос на одно сохранение.
"""

from typing import Any

from sqladmin import ModelView, action
from sqlalchemy import Select, delete, select
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from starlette.requests import Request
from starlette.responses import RedirectResponse
from wtforms import SelectField, StringField
from wtforms.validators import Optional as OptionalValue

from app.admin.money import kop_to_rub, rub_to_kop
from app.catalog import paths
from app.catalog.landings import generate_landings
from app.catalog.models import Category, FilterLanding, Price, Product, Unit
from app.catalog.nav import reset_nav_cache
from app.catalog.repository import FILTERABLE_COLUMNS
from app.catalog.utils import normalize_search, slugify
from app.core.db import SessionLocal
from app.core.templating import format_rub

UNIT_CHOICES = [(u.value, {"m": "Метр", "t": "Тонна", "pcs": "Штука", "m2": "Квадратный метр"}[u.value]) for u in Unit]

SEO_LABELS: dict[str | InstrumentedAttribute[Any], str] = {
    "h1": "H1 (пусто — название)",
    "title": "Title (пусто — по шаблону)",
    "description": "Description (пусто — по шаблону)",
    "seo_text": "SEO-текст (HTML)",
}
SEO_HELP = {
    "title": {"description": "Оставьте пустым: соберётся «<название> купить в Москве…» с ценой «от»."},
    "description": {"description": "Оставьте пустым: соберётся по шаблону из названия и цены."},
    "slug": {"description": "Часть адреса латиницей. Пусто — сделаем из названия. Смена адреса создаёт 301-редирект."},
}


def clean_text(value: Any) -> str:
    """Значение поля формы → строка без пробелов по краям (None → «»)."""
    return str(value or "").strip()


class CategoryAdmin(ModelView, model=Category):
    name = "Раздел"
    name_plural = "Разделы"
    icon = "fa-solid fa-folder-tree"
    category = "Каталог"

    column_list = [Category.name, Category.path, Category.parent, Category.sort, Category.is_active]
    column_labels = {
        "name": "Название",
        "path": "Адрес",
        "parent": "Родитель",
        "sort": "Порядок",
        "is_active": "Активен",
        "slug": "Slug",
        **SEO_LABELS,
    }
    column_searchable_list = [Category.name, Category.path]
    column_sortable_list = [Category.name, Category.path, Category.sort]
    column_default_sort = [(Category.path, False)]
    column_formatters = {Category.path: lambda m, a: paths.url(m.path)}
    form_columns = [
        Category.name,
        Category.slug,
        Category.parent,
        Category.sort,
        Category.is_active,
        Category.h1,
        Category.title,
        Category.description,
        Category.seo_text,
    ]
    form_args = {"slug": {**SEO_HELP["slug"], "validators": []}, **{k: v for k, v in SEO_HELP.items() if k != "slug"}}
    form_widget_args = {"seo_text": {"rows": 10}}
    form_ajax_refs = {"parent": {"fields": ("name", "path"), "order_by": "path"}}
    # Раздел не удаляем: снимите «Активен» — адрес начнёт перенаправлять на родительский раздел
    can_delete = False

    async def on_model_change(self, data: dict, model: Category, is_created: bool, request: Request) -> None:
        data["slug"] = slugify(clean_text(data.get("slug")) or clean_text(data.get("name")))
        if not data["slug"]:
            raise ValueError("Укажите название раздела")
        parent_id = data.get("parent") or None
        async with SessionLocal() as session:
            parent_path = await paths.parent_path(session, parent_id)
            if (
                not is_created
                and parent_path
                and (parent_path == model.path or parent_path.startswith(model.path + "/"))
            ):
                raise ValueError("Раздел нельзя вложить в самого себя или в свой подраздел")
            new_path = f"{parent_path}/{data['slug']}" if parent_path else data["slug"]
            if await paths.path_taken(session, new_path, exclude=None if is_created else model):
                raise ValueError(f"Адрес {paths.url(new_path)} уже занят другой страницей")
        request.state.old_path = None if is_created else model.path
        data["path"] = new_path

    async def after_model_change(self, data: dict, model: Category, is_created: bool, request: Request) -> None:
        old = request.state.old_path
        if old and old != model.path:
            async with SessionLocal() as session:
                await paths.add_redirect(session, old, model.path)
                await paths.move_tree(session, old, model.path)
                await session.commit()
                await generate_landings(session)
        reset_nav_cache()


# Цены прямо в форме товара, в рублях. В базе — копейки в таблице prices (точные расчёты без округлений).
PRICE_FIELDS = (
    ("price_m", Unit.METER, "Цена за метр, ₽"),
    ("price_t", Unit.TON, "Цена за тонну, ₽"),
    ("price_pcs", Unit.PIECE, "Цена за штуку, ₽"),
    ("price_m2", Unit.SQUARE_METER, "Цена за м², ₽"),
)


class ProductAdmin(ModelView, model=Product):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"
    category = "Каталог"
    page_size = 50

    column_list = [Product.name, Product.category, "price_summary", Product.in_stock, Product.is_active]
    column_labels = {
        "name": "Название",
        "category": "Раздел",
        "prices": "Цены",
        "price_summary": "Цены",
        "in_stock": "В наличии",
        "is_active": "Активен",
        "slug": "Slug",
        "sku": "Артикул",
        "steel_grade": "Марка стали / класс",
        "gost": "ГОСТ / ТУ",
        "diameter_mm": "Диаметр, мм",
        "width_mm": "Ширина, мм",
        "height_mm": "Высота, мм",
        "thickness_mm": "Толщина / стенка, мм",
        "length_m": "Длина прутка / трубы, м",
        "weight_per_m_kg": "Вес 1 м, кг",
        "weight_per_piece_kg": "Вес 1 шт., кг",
        "piece_length_m": "Длина 1 шт., м",
        "base_unit": "Основная единица продажи",
        "attrs": "Доп. свойства (JSON)",
        "path": "Адрес",
        **SEO_LABELS,
    }
    column_searchable_list = [Product.name, Product.sku, Product.path]
    column_sortable_list = [Product.name, Product.in_stock, Product.is_active]
    column_default_sort = [(Product.path, False)]
    form_columns = [
        Product.name,
        Product.slug,
        Product.category,
        Product.sku,
        Product.steel_grade,
        Product.gost,
        Product.diameter_mm,
        Product.width_mm,
        Product.height_mm,
        Product.thickness_mm,
        Product.length_m,
        Product.weight_per_m_kg,
        Product.weight_per_piece_kg,
        Product.piece_length_m,
        Product.base_unit,
        Product.in_stock,
        Product.is_active,
        Product.attrs,
        Product.h1,
        Product.title,
        Product.description,
        Product.seo_text,
    ]
    form_args = {
        "slug": {**SEO_HELP["slug"], "validators": []},
        "attrs": {"description": 'Например {"profile": "angle"} — какой чертёж сечения рисовать.'},
        "base_unit": {"choices": UNIT_CHOICES, "description": "В ней считается цена «от» и итог калькулятора."},
        "length_m": {"description": "Нужна для расчёта прутков и резки в калькуляторе."},
        "weight_per_m_kg": {"description": "Нужен для пересчёта в килограммы и цены за тонну."},
        "weight_per_piece_kg": {
            "description": "Для штучных товаров (лист, свая): по нему подбирается машина доставки."
        },
        "piece_length_m": {
            "description": "Самая длинная сторона одной штуки: лист 1250×2500 — 2,5 м. Для подбора машины."
        },
        **{k: v for k, v in SEO_HELP.items() if k != "slug"},
    }
    form_widget_args = {"seo_text": {"rows": 10}}
    form_overrides = {"base_unit": SelectField}
    form_ajax_refs = {"category": {"fields": ("name", "path"), "order_by": "path"}}
    can_delete = False  # снимите «Активен» — адрес начнёт перенаправлять в раздел

    # Связи не грузятся сами (lazy="raise"). Раздел в списке и карточке sqladmin грузит сам; цены (колонка «Цены»,
    # поля цен в форме) и раздел в форме (поле с поиском sqladmin не грузит) — явно
    def list_query(self, request: Request) -> Select:
        return super().list_query(request).options(selectinload(Product.prices))

    def details_query(self, request: Request) -> Select:
        return super().details_query(request).options(selectinload(Product.prices))

    def form_edit_query(self, request: Request) -> Select:
        return super().form_edit_query(request).options(selectinload(Product.category), selectinload(Product.prices))

    async def scaffold_form(self, rules=None):
        """Стандартная форма + поля цен сразу после «Основной единицы продажи»."""
        base = await super().scaffold_form(rules)
        anchor = base.base_unit.creation_counter
        extra = {}
        for i, (field, _unit, label) in enumerate(PRICE_FIELDS, start=1):
            unbound = StringField(
                label,
                validators=[OptionalValue()],
                description="Например 43,25 или 48 700. Пусто — такой цены нет." if i == 1 else "",
                render_kw={"inputmode": "decimal", "autocomplete": "off", "class": "form-control"},
            )
            unbound.creation_counter = anchor + i / 10  # порядок полей в форме
            extra[field] = unbound
        return type("ProductFormWithPrices", (base,), extra)

    async def get_form_data_for_edit(self, obj: Product) -> dict[str, Any]:
        data = await super().get_form_data_for_edit(obj)
        current = {p.unit: p.amount_kop for p in obj.prices}
        for field, unit, _label in PRICE_FIELDS:
            data[field] = kop_to_rub(current[unit]) if unit in current else ""
        return data

    async def on_model_change(self, data: dict, model: Product, is_created: bool, request: Request) -> None:
        # Поля цен не являются колонками товара: забираем их до сохранения, записываем в after_model_change
        request.state.price_input = {unit: rub_to_kop(data.pop(field, None)) for field, unit, _label in PRICE_FIELDS}
        name = clean_text(data.get("name"))
        data["slug"] = slugify(clean_text(data.get("slug")) or name)
        async with SessionLocal() as session:
            category_path = await paths.parent_path(session, data.get("category"))
            if not category_path:
                raise ValueError("Выберите раздел")
            unchanged = (
                not is_created
                and data["slug"] == model.slug
                and str(data.get("category")) == str(model.category_id)
                and data.get("name") == model.name
            )
            # Раздел, slug и название те же — адрес не трогаем (товар может лежать внутри посадочной размера)
            new_path = model.path if unchanged else f"{category_path}/{data['slug']}"
            if not unchanged and await paths.path_taken(session, new_path, exclude=None if is_created else model):
                raise ValueError(f"Адрес {paths.url(new_path)} уже занят другой страницей")
        request.state.old_path = None if is_created else model.path
        data["path"] = new_path
        data["search_text"] = normalize_search(
            " ".join(clean_text(data.get(k)) for k in ("name", "sku", "steel_grade", "gost"))
        )

    async def after_model_change(self, data: dict, model: Product, is_created: bool, request: Request) -> None:
        old = request.state.old_path
        async with SessionLocal() as session:
            await self._save_prices(session, model, request.state.price_input)
            await session.commit()
            # Новый размер — новая посадочная; товар переезжает внутрь посадочной своего размера. Адрес до переезда
            # существовал только внутри этого сохранения — редирект с него не нужен (fresh_ids), ставим один:
            # со старого адреса на итоговый
            await generate_landings(session, fresh_ids={model.id})
            final = await session.scalar(select(Product.path).where(Product.id == model.id))
            if old and final and old != final:
                await paths.add_redirect(session, old, final)
                await session.commit()

    @staticmethod
    async def _save_prices(session, model: Product, wanted: dict[Unit, int | None]) -> None:
        """Цены из формы: заполнено — создать или обновить, пусто — удалить цену за эту единицу."""
        existing = {p.unit: p for p in await session.scalars(select(Price).where(Price.product_id == model.id))}
        for unit, kop in wanted.items():
            if kop is None:
                if unit in existing:
                    await session.execute(delete(Price).where(Price.id == existing[unit].id))
            elif unit in existing:
                existing[unit].amount_kop = kop
            else:
                session.add(Price(product_id=model.id, unit=unit, amount_kop=kop))


class PriceAdmin(ModelView, model=Price):
    name = "Цена"
    name_plural = "Цены"
    icon = "fa-solid fa-ruble-sign"
    category = "Каталог"
    page_size = 50

    column_list = [Price.product, Price.unit, Price.amount_kop]
    column_labels = {"product": "Товар", "unit": "Единица", "amount_kop": "Цена"}
    column_formatters = {
        Price.amount_kop: lambda m, a: format_rub(m.amount_kop),
        Price.unit: lambda m, a: m.unit.label,
    }
    form_columns = [Price.product, Price.unit, Price.amount_kop]
    form_overrides = {"unit": SelectField}
    form_args = {
        "amount_kop": {"label": "Цена в копейках", "description": "4325 = 43,25 ₽, 4870000 = 48 700 ₽"},
        "unit": {"choices": UNIT_CHOICES},
    }
    form_ajax_refs = {"product": {"fields": ("name", "sku"), "order_by": "name"}}


class FilterLandingAdmin(ModelView, model=FilterLanding):
    name = "Посадочная"
    name_plural = "Посадочные (SEO-фильтры)"
    icon = "fa-solid fa-filter"
    category = "Каталог"

    column_list = [
        FilterLanding.name,
        FilterLanding.path,
        FilterLanding.filters,
        FilterLanding.is_indexable,
        FilterLanding.is_generated,
    ]
    column_labels = {
        "name": "Название",
        "path": "Адрес",
        "filters": "Фильтр",
        "is_indexable": "В индексе",
        "is_generated": "Авто",
        "category": "Раздел",
        "slug": "Slug",
        "sort": "Порядок",
        **SEO_LABELS,
    }
    column_searchable_list = [FilterLanding.name, FilterLanding.path]
    column_default_sort = [(FilterLanding.path, False)]
    column_formatters = {FilterLanding.path: lambda m, a: paths.url(m.path)}
    form_columns = [
        FilterLanding.name,
        FilterLanding.slug,
        FilterLanding.category,
        FilterLanding.filters,
        FilterLanding.is_indexable,
        FilterLanding.sort,
        FilterLanding.h1,
        FilterLanding.title,
        FilterLanding.description,
        FilterLanding.seo_text,
    ]
    form_args = {
        "slug": {**SEO_HELP["slug"], "validators": []},
        "filters": {
            "description": 'JSON, например {"diameter_mm": 12} или {"width_mm": 40, "height_mm": 20}. '
            f"Ключи: {', '.join(FILTERABLE_COLUMNS)}"
        },
        "is_indexable": {
            "description": "Снимите — страница останется для людей, но получит noindex и уйдёт из sitemap."
        },
        **{k: v for k, v in SEO_HELP.items() if k != "slug"},
        "title": {"description": "{price} подставит минимальную цену: «от 43,25 ₽». Пусто — по шаблону."},
        "description": {"description": "{price} подставит минимальную цену. Пусто — по шаблону."},
    }
    form_widget_args = {"seo_text": {"rows": 10}}

    def form_edit_query(self, request: Request) -> Select:
        """Раздел в форме — поле с поиском, sqladmin его не грузит; связи не грузятся сами (lazy="raise")."""
        return super().form_edit_query(request).options(selectinload(FilterLanding.category))

    @action(
        name="generate",
        label="Обновить посадочные из каталога",
        confirmation_message="Создать посадочные под размеры из каталога и обновить автоматические? "
        "Ручные посадочные не изменятся.",
        add_in_detail=False,
    )
    async def generate(self, request: Request) -> RedirectResponse:
        async with SessionLocal() as session:
            await generate_landings(session)
        reset_nav_cache()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)

    form_ajax_refs = {"category": {"fields": ("name", "path"), "order_by": "path"}}

    async def on_model_change(self, data: dict, model: FilterLanding, is_created: bool, request: Request) -> None:
        filters = data.get("filters") or {}
        if not isinstance(filters, dict) or not filters:
            raise ValueError('Фильтр — JSON-объект, например {"diameter_mm": 12}')
        unknown = set(filters) - set(FILTERABLE_COLUMNS)
        if unknown:
            raise ValueError(f"Неизвестные ключи фильтра: {', '.join(sorted(unknown))}")
        data["slug"] = slugify(clean_text(data.get("slug")) or clean_text(data.get("name")))
        async with SessionLocal() as session:
            category_path = await paths.parent_path(session, data.get("category"))
            if not category_path:
                raise ValueError("Выберите раздел")
            new_path = f"{category_path}/{data['slug']}"
            if await paths.path_taken(session, new_path, exclude=None if is_created else model):
                raise ValueError(f"Адрес {paths.url(new_path)} уже занят другой страницей")
        request.state.old_path = None if is_created else model.path
        data["path"] = new_path
        # Правка руками: генератор больше не трогает эту посадочную
        model.is_generated = False

    async def after_model_change(self, data: dict, model: FilterLanding, is_created: bool, request: Request) -> None:
        old = request.state.old_path
        async with SessionLocal() as session:
            if old and old != model.path:
                await paths.add_redirect(session, old, model.path)
                await paths.move_tree(session, old, model.path)  # товары внутри посадочной
                await session.commit()
            await generate_landings(session)

    async def after_model_delete(self, model: FilterLanding, request: Request) -> None:
        # Удалённая посадочная перенаправляет в свой раздел, а не отдаёт 404
        async with SessionLocal() as session:
            await paths.add_redirect(session, model.path, model.path.rsplit("/", 1)[0])
            await session.commit()
