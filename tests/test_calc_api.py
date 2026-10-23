import pytest
from sqlalchemy import func, select

from app.catalog.models import Product
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.leads.phone import normalize_phone
from tests.helpers import PageInfo

PRODUCT_URL = "/catalog/armatura/12-mm/12-mm-a500s/"
FETCH = {"X-Requested-With": "fetch"}


async def product_id() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == PRODUCT_URL.strip("/").removeprefix("catalog/")))


async def lead_count() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count(Lead.id)))


async def test_product_page_shows_default_calculation(client):
    r = await client.get(PRODUCT_URL)
    assert r.status_code == 200
    assert 'id="calc"' in r.text
    assert "506,03 ₽" in r.text  # 1 пруток по умолчанию
    assert PageInfo(r.text).robots is None


async def test_product_page_calculates_without_js_and_is_noindex(client):
    r = await client.get(PRODUCT_URL, params={"cut": "1", "cut_len": "3,9", "cut_count": "10"})
    assert r.status_code == 200
    assert "2 374,10 ₽" in r.text
    page = PageInfo(r.text)
    assert page.robots == "noindex, follow"
    assert page.canonical.endswith(PRODUCT_URL)


async def test_calc_partial(client):
    pid = await product_id()
    r = await client.get(f"/api/calc/{pid}/", params={"unit": "m", "qty": "30"})
    assert r.status_code == 200
    assert r.headers["x-robots-tag"] == "noindex"
    assert "1 518,08 ₽" in r.text
    assert "<html" not in r.text  # только кусок для подстановки


async def test_calc_partial_error_message(client):
    pid = await product_id()
    r = await client.get(f"/api/calc/{pid}/", params={"cut": "1", "cut_len": "20", "cut_count": "1"})
    assert "Отрезок длиннее прутка" in r.text


async def test_calc_unknown_product(client):
    assert (await client.get("/api/calc/999999/")).status_code == 404


async def test_lead_is_saved_with_server_side_calculation(client):
    pid = await product_id()
    before = await lead_count()
    data = {
        "product_id": pid,
        "unit": "pcs",
        "qty": "3",
        "phone": "8 (916) 123-45-67",
        "name": "Сергей",
        "comment": "Подольск",
    }
    r = await client.post("/api/lead/", data=data, headers=FETCH)
    assert r.status_code == 200
    assert "принята" in r.text
    assert await lead_count() == before + 1
    async with SessionLocal() as s:
        lead = await s.scalar(select(Lead).order_by(Lead.id.desc()))
    assert lead.phone == "+79161234567"
    assert lead.name == "Сергей"
    assert lead.calc["total_kop"] == 151808  # 35,1 м × 43,25 ₽ = 1518,075 → 1518,08 ₽
    assert lead.status == "new"


async def test_lead_without_js_returns_full_page(client):
    pid = await product_id()
    r = await client.post("/api/lead/", data={"product_id": pid, "unit": "pcs", "qty": "1", "phone": "+79161234567"})
    assert r.status_code == 200
    page = PageInfo(r.text)
    assert page.h1 == ["Заявка принята"]
    assert page.robots == "noindex, nofollow"


async def test_lead_bad_phone_keeps_form(client):
    pid = await product_id()
    before = await lead_count()
    r = await client.post(
        "/api/lead/", data={"product_id": pid, "qty": "1", "phone": "123", "name": "Ира"}, headers=FETCH
    )
    assert r.status_code == 422
    assert "Проверьте номер" in r.text and 'value="Ира"' in r.text
    assert await lead_count() == before


async def test_lead_honeypot_is_not_saved(client):
    pid = await product_id()
    before = await lead_count()
    r = await client.post(
        "/api/lead/",
        data={"product_id": pid, "qty": "1", "phone": "+79161234567", "website": "spam.example"},
        headers=FETCH,
    )
    assert r.status_code == 200
    assert await lead_count() == before


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+7 916 123-45-67", "+79161234567"),
        ("8(916)1234567", "+79161234567"),
        ("9161234567", "+79161234567"),
        ("12345", None),
        ("+1 202 555 0100", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


async def test_calc_form_has_meters_only(client):
    """В форме нет переключателя «Штуки / Метры / Кг»: количество — в метрах, по умолчанию один пруток."""
    html = (await client.get(PRODUCT_URL)).text
    form = html.split('class="calc"', 1)[1].split("</form>", 1)[0]
    assert 'type="radio"' not in form and "Кг" not in form and "Штуки" not in form
    assert '<input type="hidden" name="unit" value="m">' in form
    assert "Количество, м" in form and 'placeholder="11,7"' in form


async def test_lead_with_file_instead_of_text_is_rejected(client):
    """Файл в поле формы (так делают боты и сканеры) — понятный отказ, а не ошибка 500."""
    pid = await product_id()
    before = await lead_count()
    data = {"product_id": pid, "unit": "pcs", "phone": "8 (916) 123-45-67"}
    r = await client.post("/api/lead/", data=data, files={"qty": ("qty.txt", b"3")}, headers=FETCH)
    assert r.status_code == 422
    assert await lead_count() == before
