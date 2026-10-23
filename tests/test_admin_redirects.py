"""Переименование товара внутри посадочной в админке — один редирект: со старого адреса на итоговый.

Сохранение идёт в два шага: админка собирает адрес по разделу товара (`armatura/a500c/<slug>`), затем генератор
посадочных переносит товар в посадочную размера (`armatura/8-mm/<slug>`). Промежуточный адрес существует только
внутри одного сохранения, посетители и поисковики его не видели — редиректа с него быть не должно,
иначе каждое переименование засоряет таблицу редиректов.
"""

import pytest_asyncio
from sqlalchemy import delete, or_, select, update

from app.admin.money import kop_to_rub
from app.catalog.models import Product, Redirect
from app.core.db import SessionLocal

PATH = "armatura/8-mm/8-mm-a500s"  # раздел — armatura/a500c, лежит в посадочной armatura/8-mm
NEW_SLUG = "8-mm-a500s-rename"


def edit_form(product: Product, **changes: str) -> dict[str, str]:
    """Форма редактирования товара со всеми текущими значениями: пустое поле стёрло бы размер или цену."""
    text = lambda value: "" if value is None else str(value)  # noqa: E731
    prices = {p.unit.value: kop_to_rub(p.amount_kop) for p in product.prices}
    form = {
        "name": product.name,
        "slug": product.slug,
        "category": str(product.category_id),
        "base_unit": product.base_unit.value,
        "attrs": "{}",
        **{
            field: text(getattr(product, field))
            for field in (
                "sku",
                "steel_grade",
                "gost",
                "diameter_mm",
                "width_mm",
                "height_mm",
                "thickness_mm",
                "length_m",
                "weight_per_m_kg",
                "weight_per_piece_kg",
                "piece_length_m",
                "h1",
                "title",
                "description",
                "seo_text",
            )
        },
        **{f"price_{unit}": prices.get(unit, "") for unit in ("m", "t", "pcs", "m2")},
    }
    if product.in_stock:
        form["in_stock"] = "y"
    if product.is_active:
        form["is_active"] = "y"
    return {**form, **changes}


@pytest_asyncio.fixture
async def product():
    async with SessionLocal() as s:
        item = await s.scalar(select(Product).where(Product.path == PATH))
    yield item
    async with SessionLocal() as s:  # вернуть товар на место и убрать редиректы теста
        await s.execute(update(Product).where(Product.id == item.id).values(slug=item.slug, path=PATH))
        await s.execute(
            delete(Redirect).where(
                or_(
                    Redirect.from_path.contains(NEW_SLUG),
                    Redirect.to_path.contains(NEW_SLUG),
                    Redirect.from_path == f"/catalog/{PATH}/",
                )
            )
        )
        await s.commit()


async def test_rename_inside_landing_leaves_one_redirect(admin, product):
    r = await admin.post(f"/admin/product/edit/{product.id}", data=edit_form(product, slug=NEW_SLUG))
    assert r.status_code == 302, r.text[:500]
    async with SessionLocal() as s:
        final = await s.scalar(select(Product.path).where(Product.id == product.id))
        to_final = set(await s.scalars(select(Redirect.from_path).where(Redirect.to_path == f"/catalog/{final}/")))
    assert final == f"armatura/8-mm/{NEW_SLUG}"  # товар остался в посадочной размера
    assert to_final == {f"/catalog/{PATH}/"}  # только со старого адреса, без промежуточного armatura/a500c/…
