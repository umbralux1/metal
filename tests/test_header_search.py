"""Поиск в шапке: на телефоне свёрнут в лупу, на странице результатов открыт сразу."""

import re


async def test_search_toggle_works_without_js(client):
    html = (await client.get("/contacts/")).text
    toggle = re.search(r'<a class="search-toggle"[^>]*>', html)
    assert toggle, "нет кнопки-лупы"
    # Без JavaScript лупа ведёт на страницу поиска; управляет формой шапки
    assert 'href="/search/"' in toggle.group(0)
    assert 'aria-controls="site-search"' in toggle.group(0)
    assert 'id="site-search"' in html
    assert 'class="site-header"' in html  # на обычных страницах поиск свёрнут


async def test_search_page_keeps_header_search_open(client):
    html = (await client.get("/search/", params={"q": "труба"})).text
    assert 'class="site-header is-search-open"' in html
