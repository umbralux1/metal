"""Правила «Безопасность» из CLAUDE.md, которые проверяются запросом к сайту."""

import pytest


@pytest.mark.parametrize("path", ["//evil.com/Catalog", "///evil.com/x", "//evil.com/catalog//armatura"])
async def test_canonical_redirect_stays_on_site(client, path):
    """Исправление адреса (регистр, слэши) не уводит на чужой домен: Location — свой путь от корня."""
    r = await client.get(path)
    location = r.headers.get("location", "")
    assert not location.startswith("//") and "://" not in location, location
