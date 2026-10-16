"""Список контактов у телефона в шапке и на странице /contacts/."""

import re

from app.core.config import Settings, settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_phones_and_emails_lists():
    s = _settings(
        phone="+7 (495) 111-11-11",
        extra_phones="+7 (916) 222-22-22; +7 (495) 111-11-11, ",
        email="a@metall.ru",
        extra_emails="b@metall.ru",
    )
    assert s.phones == ["+7 (495) 111-11-11", "+7 (916) 222-22-22"]  # основной первым, без повторов
    assert s.emails == ["a@metall.ru", "b@metall.ru"]


def test_messengers_links():
    s = _settings(telegram="@metall_bot", whatsapp="+7 916 000-00-00", max_url="https://max.ru/u/abc123")
    assert s.messengers == [
        ("telegram", "Telegram", "https://t.me/metall_bot"),
        ("whatsapp", "WhatsApp", "https://wa.me/79160000000"),
        ("max", "MAX", "https://max.ru/u/abc123"),
    ]
    # Пусто или чужой адрес вместо ссылки MAX — активной кнопки нет
    assert _settings(max_url="max.ru/u/abc").messengers == []
    assert _settings().messengers == []


async def test_header_dropdown_lists_all_contacts(client, monkeypatch):
    monkeypatch.setattr(settings, "extra_phones", "+7 (916) 222-22-22")
    monkeypatch.setattr(settings, "extra_emails", "zakaz@metall.ru")
    monkeypatch.setattr(settings, "telegram", "metall")
    monkeypatch.setattr(settings, "max_url", "https://max.ru/u/abc123")
    html = (await client.get("/catalog/")).text
    panel = re.search(r'<details class="contact-dd">(.*?)</details>', html, re.S)
    assert panel, "нет списка контактов в шапке"
    body = panel.group(1)
    assert 'href="tel:+79162222222"' in body and "mailto:zakaz@metall.ru" in body
    assert 'href="https://t.me/metall"' in body and 'href="https://max.ru/u/abc123"' in body
    # WhatsApp не задан — значок есть, но без ссылки
    assert "wa.me" not in body
    assert re.search(r'<span class="messenger messenger-whatsapp is-disabled" aria-disabled="true"', body)
    assert 'href="/contacts/"' in body


async def test_contacts_page_lists_extra_contacts(client, monkeypatch):
    monkeypatch.setattr(settings, "extra_phones", "+7 (916) 222-22-22")
    monkeypatch.setattr(settings, "whatsapp", "79160000000")
    html = (await client.get("/contacts/")).text
    main = html.split('<main id="main"', 1)[1]
    assert "Телефоны" in main and 'href="tel:+79162222222"' in main
    assert 'href="https://wa.me/79160000000"' in main


def test_messenger_slots_always_list_all_three():
    s = _settings(telegram="metall")
    assert s.messenger_slots == [
        ("telegram", "Telegram", "https://t.me/metall"),
        ("whatsapp", "WhatsApp", ""),
        ("max", "MAX", ""),
    ]
