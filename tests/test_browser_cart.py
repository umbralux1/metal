"""Корзина в браузере: то, что делает JavaScript (specs/002-cart-checkout).

- «В корзину» без перезагрузки: уведомление с товаром и суммой, счётчик в шапке;
- ошибка расчёта видна у кнопки, корзина не меняется;
- форма заказа: самовывоз прячет адрес и машины, организация показывает название, ИНН и оплату по счёту.

Браузер WebKit (движок Safari) ставится один раз: `make browsers`.
"""

from playwright.async_api import async_playwright, expect

REBAR = "/catalog/armatura/12-mm/12-mm-a500s/"


async def open_product(p, live_server):
    browser = await p.webkit.launch()
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await page.goto(f"{live_server}{REBAR}")
    return browser, page


async def test_add_to_cart_without_reload_shows_toast_and_counter(live_server):
    """002:FR-002: «В корзину» — без перехода, уведомление «что и на сколько», счётчик в шапке."""
    async with async_playwright() as p:
        browser, page = await open_product(p, live_server)
        await page.locator("form.calc input[name='qty']").fill("11,7")
        await page.locator("form.calc [data-cart-add]").click()
        toast = page.locator(".cart-toast")
        await expect(toast).to_contain_text("Добавлено в корзину")
        await expect(toast.locator(".cart-toast-item")).to_contain_text("Арматура 12 мм")
        await expect(toast.locator(".cart-toast-meta")).to_contain_text("11,7 м")
        await expect(toast.locator(".cart-toast-meta")).to_contain_text("₽")
        await expect(page.locator(".header-main [data-cart-count]").first).to_have_text("1")
        assert page.url.endswith(REBAR)  # страница не перезагрузилась
        await browser.close()


async def test_add_to_cart_error_is_shown_and_cart_stays_empty(live_server):
    """002:FR-004: количество не считается — ошибка у кнопки, в корзину ничего не попало."""
    async with async_playwright() as p:
        browser, page = await open_product(p, live_server)
        await page.locator("form.calc input[name='qty']").fill("0")
        await page.locator("form.calc [data-cart-add]").click()
        status = page.locator("form.calc [data-cart-status]")
        await expect(status).to_be_visible()
        await expect(status).to_have_class("calc-error")
        await expect(page.locator(".cart-toast")).to_have_count(0)
        await page.goto(f"{live_server}/cart/")
        await expect(page.get_by_text("В корзине пока ничего нет")).to_be_visible()
        await browser.close()


async def test_checkout_form_shows_fields_for_choice(live_server):
    """002:FR-012, 002:FR-013: самовывоз прячет адрес; организация — название, ИНН, оплата по счёту."""
    async with async_playwright() as p:
        browser, page = await open_product(p, live_server)
        await page.locator("form.calc input[name='qty']").fill("11,7")
        await page.locator("form.calc [data-cart-add]").click()
        await expect(page.locator(".cart-toast")).to_be_visible()
        await page.goto(f"{live_server}/cart/")

        address = page.locator(".checkout-form input[name='address']")
        await expect(address).to_be_visible()  # по умолчанию — доставка
        await page.locator("input[name='delivery'][value='pickup']").check()
        await expect(address).to_be_hidden()
        await page.locator("input[name='delivery'][value='delivery']").check()
        await expect(address).to_be_visible()

        inn = page.locator(".checkout-form input[name='inn']")
        invoice = page.locator("input[name='payment'][value='invoice']")
        await expect(inn).to_be_hidden()
        await page.locator("input[name='buyer_type'][value='company']").check()
        await expect(inn).to_be_visible()
        await invoice.check()
        await page.locator("input[name='buyer_type'][value='person']").check()
        await expect(inn).to_be_hidden()
        await expect(invoice).not_to_be_checked()  # частному лицу счёт не выставляем — вернулась оплата при получении
        await expect(page.locator("input[name='payment'][value='cash']")).to_be_checked()
        await browser.close()
