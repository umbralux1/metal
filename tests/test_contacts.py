import json
import re

from app.core import maps
from app.core.config import settings
from app.seo import jsonld


def _jsonld(html: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


async def test_contacts_page_with_city_map(client, monkeypatch):
    monkeypatch.setattr(settings, "map_lat", None)
    monkeypatch.setattr(settings, "map_lon", None)
    r = await client.get("/contacts/")
    assert r.status_code == 200
    html = r.text
    assert '<iframe src="https://yandex.ru/map-widget/v1/?ll=37.617635%2C55.755814&amp;z=10"' in html
    assert 'loading="lazy"' in html and "Построить маршрут" not in html
    assert f'<link rel="canonical" href="{settings.site_url}/contacts/">' in html
    store = next(b for b in _jsonld(html) if b["@type"] == "Store")
    assert "geo" not in store and store["telephone"] == settings.phone


async def test_contacts_page_with_pin(client, monkeypatch):
    monkeypatch.setattr(settings, "map_lat", 55.70001)
    monkeypatch.setattr(settings, "map_lon", 37.80002)
    html = (await client.get("/contacts/")).text
    assert "pt=37.800020%2C55.700010%2Cpm2rdm" in html
    assert "rtext=~55.70001%2C37.80002" in html and "Построить маршрут" in html
    store = next(b for b in _jsonld(html) if b["@type"] == "Store")
    assert store["geo"] == {"@type": "GeoCoordinates", "latitude": 55.70001, "longitude": 37.80002}


def test_map_view_without_coordinates(monkeypatch):
    monkeypatch.setattr(settings, "map_lat", None)
    monkeypatch.setattr(settings, "map_lon", 37.6)
    view = maps.yandex_map()
    assert not view.has_pin and view.route_url is None
    assert "geo" not in jsonld.local_business()


def test_empty_coordinates_from_env_file():
    from app.core.config import Settings

    s = Settings(_env_file=None, map_lat="", map_lon="")
    assert s.map_lat is None and s.map_lon is None


async def test_contacts_in_sitemap_and_footer(client):
    assert "/contacts/</loc>" in (await client.get("/sitemap.xml")).text
    assert 'href="/contacts/"' in (await client.get("/")).text
