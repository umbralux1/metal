"""Инструмент снимков для рефакторинга (`scripts/snapshot.py`, `make snapshot` / `make snapshot-diff`).

Снимок — ответы сайта, корзины и админки и записи в базе. Перед сравнением из ответов убирается то, что меняется
само (время, отпечаток `?v=…` у CSS и JS), иначе разница была бы всегда. Здесь проверяется только чистая часть:
очистка, сравнение и сохранение на диск. Обход сайта проверяется запуском `make snapshot`.
"""

from scripts.snapshot import Entry, compare, load, normalize, save


def test_normalize_drops_asset_fingerprints_and_times():
    body = (
        '<link href="/static/css/main.css?v=3f9a1c2b">'
        "<td>24.10.2026 18:58</td><td>2026-10-24 15:58:07.123456+00:00</td><td>2026-10-24T15:58:07</td>"
    )
    assert normalize(body) == '<link href="/static/css/main.css"><td><time></td><td><time></td><td><time></td>'


def test_normalize_keeps_prices_and_sizes():
    body = "<td>47,56 ₽</td><td>40х20х2</td><td>ГОСТ 34028-2016</td><td>11.7</td>"
    assert normalize(body) == body


def test_same_snapshots_have_no_difference():
    entries = [Entry("page /", 200, "", "<h1>Главная</h1>")]
    diff = compare(entries, list(entries))
    assert (diff.changed, diff.missing, diff.added) == ([], [], [])


def test_compare_finds_changed_missing_and_added():
    before = [
        Entry("page /", 200, "", "<h1>Главная</h1>"),
        Entry("page /old/", 200, "", "старая"),
        Entry("redirect /a/", 301, "/b/", ""),
    ]
    after = [
        Entry("page /", 200, "", "<h1>Главная страница</h1>"),
        Entry("redirect /a/", 301, "/c/", ""),
        Entry("page /new/", 200, "", "новая"),
    ]
    diff = compare(before, after)
    assert diff.changed == ["page /", "redirect /a/"]  # и текст, и статус с адресом редиректа
    assert diff.missing == ["page /old/"]
    assert diff.added == ["page /new/"]


def test_report_shows_changed_lines():
    before = [Entry("page /", 200, "", "<h1>Главная</h1>\n<p>Цена 10 ₽</p>")]
    after = [Entry("page /", 200, "", "<h1>Главная</h1>\n<p>Цена 12 ₽</p>")]
    report = "\n".join(compare(before, after).report(before, after))
    assert "page /" in report
    assert "-<p>Цена 10 ₽</p>" in report
    assert "+<p>Цена 12 ₽</p>" in report


def test_saved_snapshot_loads_back(tmp_path):
    entries = [
        Entry("page /", 200, "", "<h1>Главная</h1>"),
        Entry("redirect /a/", 301, "/b/", ""),
        Entry("calc 1", 200, "", "<h1>Главная</h1>"),  # одинаковые ответы на диске хранятся один раз
    ]
    save(entries, tmp_path / "before")
    assert load(tmp_path / "before") == entries
