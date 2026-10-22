"""Вес и длина одной штуки у товара — для подбора машины доставки (листы, профнастил, сваи).

У длинномеров (пруток, труба) вес и длина уже есть: «Вес 1 м» и «Длина прутка». У штучных товаров
их не было, и вес корзины с листами было не посчитать. Колонки: weight_per_piece_kg, piece_length_m.
Пусто — вес или длина неизвестны: машину для такого заказа подтвердит менеджер.
"""

from decimal import Decimal

import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.catalog.demo_catalog import _tree, _walk
from app.catalog.models import Category, Product
from app.core.db import SessionLocal
from tests.helpers import run_alembic

TEST_NAME = "Лист тестовый 3 мм 1500х6000"


def demo_items() -> dict[str, dict]:
    return {item.name: item.fields for _path, node, _ in _walk(_tree()) for item in node.items}


# ---------- Модель ----------


@pytest.mark.parametrize("column", ["weight_per_piece_kg", "piece_length_m"])
@pytest.mark.parametrize("value", [Decimal(0), Decimal(-1)])
async def test_db_rejects_non_positive(column, value):
    async with SessionLocal() as session:
        category = await session.scalar(select(Category).where(Category.path == "armatura"))
        session.add(Product(category_id=category.id, path="armatura/test-piece", name="Тест", **{column: value}))
        with pytest.raises(IntegrityError):
            await session.commit()


# ---------- Админка ----------


async def test_admin_form_has_piece_fields_after_weight_per_meter(admin):
    async with SessionLocal() as session:
        item = await session.scalar(select(Product).where(Product.path.like("armatura/%")).limit(1))
    form = (await admin.get(f"/admin/product/edit/{item.id}")).text
    assert "Вес 1 шт., кг" in form and "Длина 1 шт., м" in form
    assert form.index('name="weight_per_m_kg"') < form.index('name="weight_per_piece_kg"')
    assert form.index('name="weight_per_piece_kg"') < form.index('name="piece_length_m"')
    assert form.index('name="piece_length_m"') < form.index('name="base_unit"')


async def test_admin_saves_piece_fields(admin):
    async with SessionLocal() as session:
        category = await session.scalar(select(Category).where(Category.path == "armatura"))
    data = {
        "name": TEST_NAME,
        "slug": "",
        "category": str(category.id),
        "base_unit": "pcs",
        "weight_per_piece_kg": "211.95",
        "piece_length_m": "6",
        "in_stock": "y",
        "is_active": "y",
        "attrs": "{}",
        "price_pcs": "15000",
    }
    try:
        r = await admin.post("/admin/product/create", data=data)
        assert r.status_code == 302, r.text[:500]
        async with SessionLocal() as session:
            product = await session.scalar(select(Product).where(Product.name == TEST_NAME))
        assert product.weight_per_piece_kg == Decimal("211.95")
        assert product.piece_length_m == Decimal("6")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Product).where(Product.name == TEST_NAME))
            await session.commit()


# ---------- Демо-каталог ----------


def test_demo_sheets_have_weight_and_length():
    sheet = demo_items()["Лист горячекатаный 2 мм 1250х2500"]
    assert sheet["weight_per_piece_kg"] == Decimal(str(sheet["attrs"]["sheet_kg"]))
    assert sheet["piece_length_m"] == Decimal("2.5")  # длинная сторона листа


def test_demo_piles_have_length():
    pile = demo_items()["Свая винтовая 57х3,5, 2000 мм"]
    assert pile["piece_length_m"] == Decimal("2")
    assert "weight_per_piece_kg" not in pile  # вес сваи неизвестен — не выдумываем


def test_every_demo_sheet_with_format_has_size():
    for name, fields in demo_items().items():
        attrs = fields.get("attrs") or {}
        if "sheet_kg" in attrs:
            assert fields.get("weight_per_piece_kg"), name
            assert fields.get("piece_length_m"), name


# ---------- Миграция: заполняет уже существующие товары ----------


def test_migration_fills_existing_sheets_and_piles(migrations_db):
    run_alembic("upgrade", "0004")
    with migrations_db.begin() as conn:
        cat = conn.execute(
            text("INSERT INTO categories (slug, path, name) VALUES ('list', 'list', 'Лист') RETURNING id")
        )
        cat_id = cat.scalar()
        insert = text(
            "INSERT INTO products (category_id, slug, path, name, base_unit, attrs)"
            " VALUES (:c, :s, :p, :n, 'pcs', CAST(:a AS jsonb))"
        )
        conn.execute(
            insert,
            {"c": cat_id, "s": "l", "p": "list/l", "n": "Лист", "a": '{"format": "1250×2500", "sheet_kg": 98.1}'},
        )
        conn.execute(insert, {"c": cat_id, "s": "s", "p": "list/s", "n": "Свая", "a": '{"length_mm": 2500}'})
        conn.execute(insert, {"c": cat_id, "s": "x", "p": "list/x", "n": "Хомут", "a": "{}"})

    run_alembic("upgrade", "head")
    with migrations_db.connect() as conn:
        rows = dict(conn.execute(text("SELECT slug, (weight_per_piece_kg, piece_length_m)::text FROM products")).all())
    assert rows["l"] == "(98.100,2.500)"
    assert rows["s"] == "(,2.500)"
    assert rows["x"] == "(,)"

    run_alembic("downgrade", "0004")
    migrations_db.dispose()
    columns = {c["name"] for c in inspect(migrations_db).get_columns("products")}
    assert "weight_per_piece_kg" not in columns and "piece_length_m" not in columns
    migrations_db.dispose()
