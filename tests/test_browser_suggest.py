"""BUG-005: в подсказках поиска название видно целиком, а не «Арма…».

Список подсказок был шириной с поле поиска в шапке (около 220 px на окне 1024 px). Колонки «Раздел / Размер /
Товар» и цена занимали почти всё место, и названия обрезались многоточием: «Ар…», «Арма…». Три товара
«Арматура 12 мм …» отличаются только маркой стали в конце названия — её не было видно.

Тест открывает сайт в WebKit, набирает запрос в поиске в шапке и проверяет каждую подсказку: текст названия
помещается в свою колонку (ширина текста не больше ширины колонки — значит, нет многоточия).
Браузер WebKit ставится один раз: `make browsers`.
"""

from playwright.async_api import async_playwright

QUERY = "арматура"  # разделы, страницы размеров и товары «Арматура 12 мм …»
# Названия, которые не помещаются в свою колонку: у них текст шире самой колонки
CUT_NAMES = """names => names.filter(el => el.scrollWidth > el.clientWidth).map(el => el.textContent)"""


async def test_suggestion_names_are_not_cut(live_server):
    async with async_playwright() as p:
        browser = await p.webkit.launch()
        page = await browser.new_page(viewport={"width": 1024, "height": 900})
        await page.goto(f"{live_server}/catalog/armatura/")
        await page.locator(".header-main input[name='q']").fill(QUERY)
        await page.locator(".suggest .suggest-product").first.wait_for()
        cut = await page.locator(".suggest .suggest-name").evaluate_all(CUT_NAMES)
        await browser.close()
    assert cut == [], f"на ширине 1024 px названия в подсказках обрезаны: {cut}"
