"""Разделы админки. Адреса (slug, path) и поисковый текст считаются сами при сохранении."""

from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from starlette.requests import Request
from wtforms import SelectField

from app.admin.auth import AdminAuth
from app.catalog import paths
from app.catalog.models import Category, FilterLanding, Price, Product, Redirect, Unit
from app.catalog.repository import FILTERABLE_COLUMNS
from app.catalog.utils import normalize_search, slugify
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.nav import reset_nav_cache
from app.core.templating import format_rub
from app.leads.models import Lead

UNIT_CHOICES = [(u.value, {"m": "Метр", "t": "Тонна", "pcs": "Штука", "m2": "Квадратный метр"}[u.value]) for u in Unit]

SEO_LABELS = {
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


def _clean(value: Any) -> str:
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
        data["slug"] = slugify(_clean(data.get("slug")) or _clean(data.get("name")))
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
        model._old_path = None if is_created else model.path
        data["path"] = new_path

    async def after_model_change(self, data: dict, model: Category, is_created: bool, request: Request) -> None:
        old = getattr(model, "_old_path", None)
        if old and old != model.path:
            async with SessionLocal() as session:
                await paths.add_redirect(session, old, model.path)
                await paths.move_tree(session, old, model.path)
                await session.commit()
        reset_nav_cache()


class ProductAdmin(ModelView, model=Product):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"
    category = "Каталог"
    page_size = 50

    column_list = [Product.name, Product.category, Product.prices, Product.in_stock, Product.is_active]
    column_labels = {
        "name": "Название",
        "category": "Раздел",
        "prices": "Цены",
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
        **{k: v for k, v in SEO_HELP.items() if k != "slug"},
    }
    form_widget_args = {"seo_text": {"rows": 10}}
    form_overrides = {"base_unit": SelectField}
    form_ajax_refs = {"category": {"fields": ("name", "path"), "order_by": "path"}}
    can_delete = False  # снимите «Активен» — адрес начнёт перенаправлять в раздел

    async def on_model_change(self, data: dict, model: Product, is_created: bool, request: Request) -> None:
        name = _clean(data.get("name"))
        data["slug"] = slugify(_clean(data.get("slug")) or name)
        async with SessionLocal() as session:
            category_path = await paths.parent_path(session, data.get("category"))
            if not category_path:
                raise ValueError("Выберите раздел")
            new_path = f"{category_path}/{data['slug']}"
            if await paths.path_taken(session, new_path, exclude=None if is_created else model):
                raise ValueError(f"Адрес {paths.url(new_path)} уже занят другой страницей")
        model._old_path = None if is_created else model.path
        data["path"] = new_path
        data["search_text"] = normalize_search(
            " ".join(_clean(data.get(k)) for k in ("name", "sku", "steel_grade", "gost"))
        )

    async def after_model_change(self, data: dict, model: Product, is_created: bool, request: Request) -> None:
        old = getattr(model, "_old_path", None)
        if old and old != model.path:
            async with SessionLocal() as session:
                await paths.add_redirect(session, old, model.path)
                await session.commit()


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

    column_list = [FilterLanding.name, FilterLanding.path, FilterLanding.filters, FilterLanding.is_indexable]
    column_labels = {
        "name": "Название",
        "path": "Адрес",
        "filters": "Фильтр",
        "is_indexable": "В индексе",
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
    }
    form_widget_args = {"seo_text": {"rows": 10}}
    form_ajax_refs = {"category": {"fields": ("name", "path"), "order_by": "path"}}

    async def on_model_change(self, data: dict, model: FilterLanding, is_created: bool, request: Request) -> None:
        filters = data.get("filters") or {}
        if not isinstance(filters, dict) or not filters:
            raise ValueError('Фильтр — JSON-объект, например {"diameter_mm": 12}')
        unknown = set(filters) - set(FILTERABLE_COLUMNS)
        if unknown:
            raise ValueError(f"Неизвестные ключи фильтра: {', '.join(sorted(unknown))}")
        data["slug"] = slugify(_clean(data.get("slug")) or _clean(data.get("name")))
        async with SessionLocal() as session:
            category_path = await paths.parent_path(session, data.get("category"))
            if not category_path:
                raise ValueError("Выберите раздел")
            new_path = f"{category_path}/{data['slug']}"
            if await paths.path_taken(session, new_path, exclude=None if is_created else model):
                raise ValueError(f"Адрес {paths.url(new_path)} уже занят другой страницей")
        model._old_path = None if is_created else model.path
        data["path"] = new_path

    async def after_model_change(self, data: dict, model: FilterLanding, is_created: bool, request: Request) -> None:
        old = getattr(model, "_old_path", None)
        if old and old != model.path:
            async with SessionLocal() as session:
                await paths.add_redirect(session, old, model.path)
                await session.commit()

    async def after_model_delete(self, model: FilterLanding, request: Request) -> None:
        # Удалённая посадочная перенаправляет в свой раздел, а не отдаёт 404
        async with SessionLocal() as session:
            await paths.add_redirect(session, model.path, model.path.rsplit("/", 1)[0])
            await session.commit()


class RedirectAdmin(ModelView, model=Redirect):
    name = "Редирект"
    name_plural = "Редиректы"
    icon = "fa-solid fa-route"
    category = "SEO"
    page_size = 100

    column_list = [Redirect.from_path, Redirect.to_path, Redirect.status_code, Redirect.created_at]
    column_labels = {"from_path": "Откуда", "to_path": "Куда", "status_code": "Код", "created_at": "Создан"}
    column_searchable_list = [Redirect.from_path, Redirect.to_path]
    column_default_sort = [(Redirect.created_at, True)]
    form_columns = [Redirect.from_path, Redirect.to_path, Redirect.status_code]
    form_args = {
        "from_path": {"description": "Старый адрес без домена, например /catalog/old-armatura/"},
        "to_path": {"description": "Новый адрес без домена, например /catalog/armatura/"},
        "status_code": {"description": "301 — переехало навсегда (обычно нужен он), 302 — временно"},
    }

    async def on_model_change(self, data: dict, model: Redirect, is_created: bool, request: Request) -> None:
        def norm(value: Any) -> str:
            value = "/" + _clean(value).lstrip("/")
            last = value.rsplit("/", 1)[-1]
            return value if value.endswith("/") or "." in last else value + "/"

        data["from_path"] = norm(data.get("from_path")).lower()
        data["to_path"] = norm(data.get("to_path"))
        if data["from_path"] == data["to_path"]:
            raise ValueError("Адрес «откуда» совпадает с «куда»")
        if int(data.get("status_code") or 301) not in (301, 302, 308):
            raise ValueError("Код — 301, 302 или 308")


LEAD_STATUSES = [("new", "Новая"), ("in_progress", "В работе"), ("done", "Выполнена"), ("spam", "Спам")]


class LeadAdmin(ModelView, model=Lead):
    name = "Заявка"
    name_plural = "Заявки"
    icon = "fa-solid fa-phone"
    category = "Продажи"
    page_size = 50

    column_list = [Lead.id, Lead.created_at, Lead.product_name, Lead.name, Lead.phone, Lead.calc, Lead.status]
    column_details_list = [
        Lead.id,
        Lead.created_at,
        Lead.product_name,
        Lead.name,
        Lead.phone,
        Lead.comment,
        Lead.calc,
        Lead.status,
    ]
    column_labels = {
        "id": "№",
        "created_at": "Когда",
        "product_name": "Товар",
        "name": "Имя",
        "phone": "Телефон",
        "calc": "Сумма",
        "status": "Статус",
        "comment": "Комментарий",
    }
    column_searchable_list = [Lead.phone, Lead.name, Lead.product_name]
    column_sortable_list = [Lead.id, Lead.created_at, Lead.status]
    column_default_sort = [(Lead.created_at, True)]
    column_formatters = {
        Lead.calc: lambda m, a: format_rub(m.calc.get("total_kop")) if m.calc else "—",
        Lead.status: lambda m, a: dict(LEAD_STATUSES).get(m.status, m.status),
        Lead.created_at: lambda m, a: m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
    }
    column_formatters_detail = {
        Lead.status: lambda m, a: dict(LEAD_STATUSES).get(m.status, m.status),
    }
    can_create = False
    form_columns = [Lead.status, Lead.comment]
    form_overrides = {"status": SelectField}
    form_args = {"status": {"choices": LEAD_STATUSES}}


def setup_admin(app: FastAPI) -> Admin | None:
    """Подключает /admin, если задан пароль. Без пароля админки нет совсем."""
    if not settings.admin_password:
        return None
    admin = Admin(
        app,
        engine=engine,
        session_maker=SessionLocal,
        authentication_backend=AdminAuth(),
        title=f"{settings.site_name} — админка",
        base_url="/admin",
    )
    for view in (CategoryAdmin, ProductAdmin, PriceAdmin, FilterLandingAdmin, RedirectAdmin, LeadAdmin):
        admin.add_view(view)
    return admin


__all__ = ["Unit", "setup_admin"]
