"""Подзадача 10: страница «Доставка» — тарифы всех активных машин для покупателей и поисковиков.

Адрес /delivery/. Тарифы берутся из таблицы машин: поменяли цену в админке — страница показывает новую.
SEO-требования (h1, title, canonical, sitemap, разметка) проверяет tests/test_seo_pages.py.
"""

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.core.templating import format_rub
from app.delivery.models import DeliveryVehicle

URL = "/delivery/"


async def test_page_lists_active_vehicles_with_tariffs(client):
    r = await client.get(URL)
    assert r.status_code == 200
    html = r.text
    assert "<h1>Доставка металлопроката</h1>" in html
    for name in ("Грузовик до 1,2 т", "Грузовик до 5 т", "Манипулятор до 10 т", "Длинномер до 25 т"):
        assert name in html
    assert format_rub(185_000) in html and format_rub(13_000) in html  # грузовик до 1,2 т: база и за км
    assert format_rub(1_850_000) in html  # длинномер
    assert "13,5 м" in html  # длина кузова длинномера
    assert html.index("Грузовик до 1,2 т") < html.index("Длинномер до 25 т")  # по полю «Порядок»


async def test_page_explains_formula_and_limits(client):
    html = (await client.get(URL)).text
    assert "каждый начатый километр" in html
    assert "200 км" in html  # предел DELIVERY_MAX_KM
    assert "Самовывоз" in html


async def test_inactive_vehicle_is_hidden_and_price_changes_show(client):
    async with SessionLocal() as s:
        crane = await s.scalar(select(DeliveryVehicle).where(DeliveryVehicle.name == "Манипулятор до 10 т"))
        truck = await s.scalar(select(DeliveryVehicle).where(DeliveryVehicle.name == "Грузовик до 5 т"))
        await s.execute(update(DeliveryVehicle).where(DeliveryVehicle.id == crane.id).values(is_active=False))
        await s.execute(update(DeliveryVehicle).where(DeliveryVehicle.id == truck.id).values(base_price_kop=250_000))
        await s.commit()
        try:
            html = (await client.get(URL)).text
            assert "Манипулятор до 10 т" not in html
            assert format_rub(250_000) in html  # новая базовая цена грузовика до 5 т — без перезапуска
        finally:
            await s.execute(update(DeliveryVehicle).where(DeliveryVehicle.id == crane.id).values(is_active=True))
            await s.execute(
                update(DeliveryVehicle).where(DeliveryVehicle.id == truck.id).values(base_price_kop=240_000)
            )
            await s.commit()


async def test_footer_links_to_delivery(client):
    html = (await client.get("/")).text
    assert f'href="{URL}"' in html
