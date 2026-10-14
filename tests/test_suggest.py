"""Автодополнение поиска: разделы, размеры, товары, исправление раскладки."""

import pytest

from app.catalog.utils import fix_layout


async def _suggest(client, q):
    r = await client.get("/api/suggest/", params={"q": q})
    assert r.status_code == 200
    return r


async def test_suggest_categories_landings_and_products(client):
    data = (await _suggest(client, "армат")).json()
    kinds = [i["kind"] for i in data["items"]]
    assert kinds[0] == "category" and data["items"][0]["url"] == "/catalog/armatura/"
    assert "landing" in kinds and "product" in kinds
    product = next(i for i in data["items"] if i["kind"] == "product")
    assert product["url"].startswith("/catalog/armatura/") and "₽" in product["meta"]


async def test_suggest_size_with_any_separator(client):
    for q in ("труба 40х20", "труба 40x20", "труба 40*20"):
        data = (await _suggest(client, q)).json()
        names = [i["name"] for i in data["items"]]
        assert "Труба профильная 40х20" in names, q  # посадочная размера
        assert any(n.startswith("Труба профильная 40х20х") for n in names), q  # товары размера


async def test_suggest_fixes_keyboard_layout(client):
    data = (await _suggest(client, "fhvfnehf")).json()
    assert data["corrected"] == "арматура"
    assert data["items"] and data["items"][0]["name"] == "Арматура"


async def test_suggest_short_query_and_headers(client):
    r = await _suggest(client, "а")
    assert r.json()["items"] == []
    assert r.headers["x-robots-tag"] == "noindex"
    assert (await _suggest(client, "ничего такого нет")).json()["items"] == []


async def test_search_page_fixes_layout(client):
    r = await client.get("/search/", params={"q": "nhe,f 40x20"})
    assert "Показываем результаты для «труба 40x20»" in r.text
    assert "Труба профильная 40х20х2" in r.text


async def test_suggest_script_is_versioned_on_every_page(client):
    html = (await client.get("/contacts/")).text
    assert 'src="/static/js/suggest.js?v=' in html


@pytest.mark.parametrize(
    ("typed", "fixed"),
    [("fhvfnehf", "арматура"), ("nhe,f 40x20", "труба 40x20"), ("Арматура", None), ("12", None)],
)
def test_fix_layout(typed, fixed):
    assert fix_layout(typed) == fixed


async def test_number_does_not_match_inside_other_numbers(client):
    """«уголок 50» не находит уголки 25х25 и 40х40 только потому, что в ГОСТ 8509-93 есть «50»."""
    from app.catalog import repository as repo
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        found = [p.name for p in await repo.search_products(session, "труба 20х20")]
        assert found == ["Труба профильная 20х20х2"]
        # 12 мм ≠ 120: на странице поиска число целиком
        assert all(" 12 " in f" {p.name} " for p in await repo.search_products(session, "арматура 12"))
        # В подсказках последнее число — началом: «40х2» уже находит «40х20»
        typed = [p.name for p in await repo.search_products(session, "труба 40х2", prefix_last=True)]
        assert "Труба профильная 40х20х2" in typed
