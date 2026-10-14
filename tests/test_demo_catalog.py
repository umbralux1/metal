"""Демо-каталог: структура разделов, примеры в каждой группе, загрузка без дублей."""

import re
from collections import Counter

from sqlalchemy import func, select

from app.catalog.demo_catalog import _tree, _walk, sync_demo_catalog
from app.catalog.models import Category, Product
from app.core.db import SessionLocal

# Группы, которых по брифу нет в ассортименте (по началу слова: «оцинкованная» — не ковка)
EXCLUDED = re.compile(r"\b(ковк|кован|чугун|нержав|латун|медн|медь|бронз)", re.IGNORECASE)


def test_every_leaf_group_has_examples_and_names_are_unique():
    nodes = list(_walk(_tree()))
    paths = [path for path, _, _ in nodes]
    assert len(paths) == len(set(paths)), "одинаковые адреса разделов"
    for path, node, _ in nodes:
        if not node.children:
            assert node.items, f"в группе {path} нет примеров"
        names = Counter(item.name for item in node.items)
        assert max(names.values(), default=1) == 1, f"повтор товара в {path}"
    assert len(nodes) > 100


def test_brief_stop_list_is_respected():
    for path, node, _ in _walk(_tree()):
        texts = [node.name.lower(), *(item.name.lower() for item in node.items)]
        for text in texts:
            assert not EXCLUDED.search(text), f"{path}: {text}"


def test_long_products_have_weight_and_both_prices():
    for _path, node, _ in _walk(_tree()):
        for item in node.items:
            if item.unit.value == "m" and "стеклопластик" not in item.name:
                assert item.fields.get("weight_per_m_kg"), item.name
                assert {u.value for u in item.prices} == {"m", "t"}, item.name


async def test_sync_adds_catalog_once_without_duplicates():
    async with SessionLocal() as session:
        before = await session.scalar(select(func.count()).select_from(Product))
        report = await sync_demo_catalog(session, commit=False)
        assert report.categories > 90 and report.products > 200
        # Товары базового набора не дублируются: «Арматура 12 мм А500С» одна
        same = await session.scalar(
            select(func.count()).select_from(Product).where(Product.name == "Арматура 12 мм А500С")
        )
        assert same == 1
        again = await sync_demo_catalog(session, commit=False)
        assert again.categories == 0 and again.products == 0
        assert await session.scalar(select(func.count()).select_from(Category).where(Category.path == "balka/sh4")) == 1
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Product)) == before
