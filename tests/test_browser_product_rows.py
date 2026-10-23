"""BUG-004: клик в любое место строки таблицы товаров открывает этот товар, а не последний в таблице.

Строка кликалась целиком за счёт ссылки, растянутой слоем `::after` до ближайшего предка с `position`.
Safari 26 на компьютере не применяет `position: relative` к строке таблицы (вычисленное — `static`), поэтому слой
каждой ссылки растягивался на всё окно, сверху оказывался последний: строка А500С всё время подсвечена,
любой клик открывает её. В Chrome и в WebKit из Playwright строка — граница, ошибки нет.

Поведение того Safari повторяем в тесте: строкам, которые браузер показывает как строки таблицы
(`display: table-row`), задаём `position: static`, как он. Исправление не должно зависеть от того, считает ли
браузер строку таблицы границей. Браузер WebKit ставится один раз: `make browsers`.

Кликаем мышью по координатам, как человек, а не методом Playwright `click()`: тот сначала проверяет, что
элемент ничем не перекрыт, и при этой ошибке ждал бы до тайм-аута вместо того, чтобы кликнуть.
"""

import os
import socket
import subprocess
import sys
import time
from urllib.parse import quote, urlparse

import httpx
import pytest
from playwright.async_api import async_playwright

SEARCH = "Арматура 12"  # три строки: А400, А1, А500С
# Как Safari 26.6: у строки таблицы position не работает, у строки-сетки — работает
SAFARI_ROWS = """() => document.querySelectorAll('.products tbody tr').forEach(tr => {
    if (getComputedStyle(tr).display === 'table-row') tr.style.setProperty('position', 'static', 'important');
})"""


@pytest.fixture(scope="module")
def live_server():
    """Сайт в отдельном процессе на свободном порту — браузеру нужен настоящий HTTP. База — тестовая."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen(  # noqa: S603 — свой сервер из своего окружения
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        env=os.environ.copy(),
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                httpx.get(url + "/", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.1)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


async def test_click_anywhere_in_row_opens_that_product(live_server):
    async with async_playwright() as p:
        browser = await p.webkit.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        search_url = f"{live_server}/search/?q={quote(SEARCH)}"
        await page.goto(search_url)
        hrefs = await page.locator("table.products tbody tr .p-name a").evaluate_all(
            "links => links.map(a => a.getAttribute('href'))"
        )
        assert len(hrefs) >= 2, "нужно хотя бы две строки, иначе ошибку не увидеть"
        opened = []
        for index in range(len(hrefs)):
            await page.goto(search_url)
            await page.evaluate(SAFARI_ROWS)
            price = page.locator("table.products tbody tr").nth(index).locator("td.p-price")
            box = await price.bounding_box()
            assert box is not None
            async with page.expect_navigation():
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            opened.append(urlparse(page.url).path)
        await browser.close()
    assert opened == hrefs, f"клик по строкам открыл {opened}, а в строках товары {hrefs}"
