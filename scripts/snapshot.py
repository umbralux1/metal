"""Снимки для рефакторинга: ответы сайта, корзины, заявок и админки до и после изменения кода.

    make snapshot        — снимок «до» в .snapshots/before
    make snapshot-diff   — снимок «после» в .snapshots/after и сравнение с «до»

Каждый снимок снимается с нуля на отдельной базе metal_snapshot (на том же сервере, что DATABASE_URL): она
пересоздаётся, строится миграциями и наполняется полным демо-каталогом, как `python main.py` с SEED_DEMO=true.
Базы из DATABASE_URL и тестовую не трогает.

В снимке (~3 900 ответов, около минуты): страницы из sitemap, вторые страницы списков, товары с резкой
и калькулятор с 11 наборами параметров, поиск и подсказки, заявки с карточки товара, сценарий корзины
и оформления, страницы и сохранения админки, записи заявок и таблиц каталога в базе.

Перед сравнением из ответов убирается то, что меняется само: время и отпечатки ?v=… у CSS и JS. Хранится
сжато (~6–7 МБ на снимок), одинаковые ответы — один раз. Вёрстку снимок не ловит: сравнивается HTML.
"""

import asyncio
import difflib
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SNAPSHOT_DB = "metal_snapshot"
SNAPSHOTS_DIR = Path(".snapshots")
ADMIN_USER, ADMIN_PASSWORD = "snapshot", "snapshot-pass"

ASSET_VERSION = re.compile(r"\?v=[0-9a-f]+")
TIME = re.compile(
    r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?"
)


@dataclass(frozen=True)
class Entry:
    """Один ответ или одна выгрузка из базы: метка, статус, адрес редиректа, текст после очистки."""

    label: str
    status: int
    location: str
    body: str


def normalize(body: str) -> str:
    """Убирает то, что меняется без изменения кода: отпечатки ?v=… у статики и время."""
    return TIME.sub("<time>", ASSET_VERSION.sub("", body))


@dataclass
class SnapshotDiff:
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    def report(self, before: list[Entry], after: list[Entry], examples: int = 3, max_lines: int = 40) -> list[str]:
        """Отчёт для человека: что отличается и изменённые строки первых `examples` ответов."""
        if not (self.changed or self.missing or self.added):
            return [f"Отличий нет: {len(after)} ответов совпали."]
        old, new = {e.label: e for e in before}, {e.label: e for e in after}
        lines = [f"Отличаются: {len(self.changed)}, пропали: {len(self.missing)}, новые: {len(self.added)}."]
        for title, labels in (("Отличаются", self.changed), ("Пропали", self.missing), ("Новые", self.added)):
            if labels:
                lines += ["", f"{title}:"] + [f"  {label}" for label in labels[:50]]
                lines += [f"  … и ещё {len(labels) - 50}"] if len(labels) > 50 else []
        for label in self.changed[:examples]:
            a, b = old[label], new[label]
            lines += ["", f"=== {label}"]
            if (a.status, a.location) != (b.status, b.location):
                lines.append(f"статус {a.status} {a.location} → {b.status} {b.location}".replace("  ", " "))
            diff = difflib.unified_diff(a.body.splitlines(), b.body.splitlines(), lineterm="", n=1)
            body = [line[:200] for line in list(diff)[2:]]  # без заголовков «---» и «+++»
            lines += body[:max_lines] + ([f"… ещё {len(body) - max_lines} строк"] if len(body) > max_lines else [])
        return lines


def compare(before: list[Entry], after: list[Entry]) -> SnapshotDiff:
    old, new = {e.label: e for e in before}, {e.label: e for e in after}
    return SnapshotDiff(
        changed=[e.label for e in before if e.label in new and new[e.label] != e],
        missing=[e.label for e in before if e.label not in new],
        added=[e.label for e in after if e.label not in old],
    )


def save(entries: list[Entry], path: Path) -> None:
    """Список ответов и тексты отдельно: одинаковые тексты (калькулятор, пустые ответы) — один раз."""
    bodies: dict[str, str] = {}
    index = []
    for e in entries:
        key = hashlib.sha1(e.body.encode()).hexdigest()  # noqa: S324 — ключ хранения, не защита
        bodies[key] = e.body
        index.append([e.label, e.status, e.location, key])
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    (path / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    (path / "bodies.json.gz").write_bytes(gzip.compress(json.dumps(bodies, ensure_ascii=False).encode()))


def load(path: Path) -> list[Entry]:
    index = json.loads((path / "index.json").read_text(encoding="utf-8"))
    bodies = json.loads(gzip.decompress((path / "bodies.json.gz").read_bytes()))
    return [Entry(label, status, location, bodies[key]) for label, status, location, key in index]


# ---------- Сбор снимка: база, сайт, заявки, корзина, админка ----------


def prepare_database() -> str:
    """Пересоздаёт metal_snapshot и строит её как `python main.py` с демо-каталогом. Возвращает её адрес."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.database_url).set(database=SNAPSHOT_DB)
    server = create_engine(url.set(database="postgres", drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SNAPSHOT_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {SNAPSHOT_DB}"))
    server.dispose()
    address = url.render_as_string(hide_password=False)
    env = {**os.environ, "DATABASE_URL": address, "SEED_DEMO": "true", "AUTO_LANDINGS": "true"}
    built = subprocess.run(  # noqa: S603 — свой запуск из своего окружения
        [sys.executable, "-c", "from app.bootstrap import prepare_database; prepare_database()"],
        env=env,
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        raise SystemExit(f"Не удалось построить базу {SNAPSHOT_DB}:\n{built.stdout}\n{built.stderr}")
    return address


class Recorder:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self._seen: dict[str, int] = {}

    def add(self, label: str, status: int, location: str, body: str) -> None:
        count = self._seen[label] = self._seen.get(label, 0) + 1
        self.entries.append(Entry(label if count == 1 else f"{label} #{count}", status, location, normalize(body)))

    def response(self, label: str, r) -> None:
        self.add(label, r.status_code, r.headers.get("location", ""), r.text)


CALC = [
    {},
    {"unit": "m", "qty": "30"},
    {"unit": "m", "qty": "7,3"},
    {"unit": "pcs", "qty": "3"},
    {"unit": "pcs", "qty": "2,5"},
    {"unit": "kg", "qty": "1500"},
    {"unit": "m", "qty": "0"},
    {"cut": "1", "cut_len": "3,9", "cut_count": "10"},
    {"cut": "1", "cut_len": "4", "cut_count": "9"},
    {"cut": "1", "cut_len": "20", "cut_count": "1"},
    {"cut": "1", "cut_len": "", "cut_count": "3"},
]
SEARCH = ["арматура", "арматура 12", "труба 40х20", "40x40", "лист 3 мм", "уголок", "fhvfnehf", "сетка", "zzz", "А500С"]
FETCH = {"X-Requested-With": "fetch"}


def site_client():
    import httpx

    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def record_site(rec: Recorder) -> None:
    """Все страницы каталога из базы, калькулятор, поиск и подсказки."""
    from sqlalchemy import select

    from app.catalog.models import Category, FilterLanding, Product
    from app.core.db import SessionLocal

    async with SessionLocal() as s:
        nodes = list(await s.scalars(select(Category.path).order_by(Category.path)))
        nodes += list(await s.scalars(select(FilterLanding.path).order_by(FilterLanding.path)))
        products = (await s.execute(select(Product.id, Product.path).order_by(Product.id))).all()
    async with site_client() as c:
        rec.response("sitemap", await c.get("/sitemap.xml"))
        for url in ["/", "/catalog/", "/contacts/", "/delivery/", "/no-such/", "/catalog/no-such/"]:
            rec.response(f"page {url}", await c.get(url))
        for path in nodes:
            rec.response(f"node /catalog/{path}/", await c.get(f"/catalog/{path}/"))
            rec.response(f"node /catalog/{path}/?page=2", await c.get(f"/catalog/{path}/", params={"page": "2"}))
        for pid, path in products:
            rec.response(f"product /catalog/{path}/", await c.get(f"/catalog/{path}/"))
            for params in CALC:
                rec.response(f"calc {path} {params}", await c.get(f"/api/calc/{pid}/", params=params))
        for q in SEARCH:
            rec.response(f"search {q}", await c.get("/search/", params={"q": q}))
            rec.response(f"suggest {q}", await c.get("/api/suggest/", params={"q": q}))


async def record_leads(rec: Recorder) -> None:
    """Форма заявки с карточки товара: ошибки, бот, заявка во всплывающем окне и отдельной страницей."""
    from sqlalchemy import select

    from app.catalog.models import Product
    from app.core.db import SessionLocal

    async with SessionLocal() as s:
        pid = await s.scalar(select(Product.id).order_by(Product.id).limit(1))
    form = {
        "product_id": pid,
        "unit": "m",
        "qty": "11,7",
        "phone": "8 916 123-45-67",
        "name": "Иван",
        "comment": "Тест",
    }
    cases = [
        ("bad-phone", {**form, "phone": "123"}, FETCH),
        ("bad-qty", {**form, "qty": "0"}, FETCH),
        ("missing-product", {**form, "product_id": 999999}, FETCH),
        ("bot", {**form, "website": "x"}, FETCH),
        ("ok-popup", form, FETCH),
        ("ok-page", form, {}),
    ]
    async with site_client() as c:
        for name, data, headers in cases:
            rec.response(f"lead {name}", await c.post("/api/lead/", data=data, headers=headers))


async def record_cart(rec: Recorder) -> None:
    """Корзина: добавление с ошибками, доставка на разные расстояния, оформление, самовывоз, бот."""
    from sqlalchemy import select

    from app.catalog.models import Product
    from app.core.db import SessionLocal
    from app.delivery.models import DeliveryVehicle

    async with SessionLocal() as s:
        rebar = await s.scalar(select(Product.id).where(Product.path.like("armatura/%12-mm-a500s")))
        truck = await s.scalar(select(DeliveryVehicle.id).where(DeliveryVehicle.name == "Грузовик до 5 т"))
        long_ = await s.scalar(select(DeliveryVehicle.id).where(DeliveryVehicle.name == "Длинномер до 25 т"))
    order = {"phone": "+79160000000", "delivery": "delivery", "address": "Подольск, Мира 5", "distance_km": "18"}
    company = {"buyer_type": "company", "company_name": "ООО «Р»", "inn": "7707083893"}
    async with site_client() as c:
        rec.response("cart empty", await c.get("/cart/"))
        bad = {"product_id": rebar, "unit": "m", "qty": "0"}
        rec.response("cart add-bad-fetch", await c.post("/cart/add/", data=bad, headers=FETCH))
        rec.response("cart add-bad", await c.post("/cart/add/", data=bad))
        rec.response("cart add-missing", await c.post("/cart/add/", data={**bad, "product_id": 999999, "qty": "1"}))
        rec.response("cart add-fetch", await c.post("/cart/add/", data={**bad, "qty": "11,7"}, headers=FETCH))
        cut = {"product_id": rebar, "unit": "m", "cut": "1", "cut_len": "2", "cut_count": "10"}
        rec.response("cart add-cut", await c.post("/cart/add/", data=cut))
        for km in ["", "18", "250", "abc"]:
            rec.response(f"cart page km={km}", await c.get("/cart/", params={"distance_km": km} if km else None))
        rec.response("cart update", await c.post("/cart/update/", data={"index": 0, "qty": "23,4"}))
        rec.response("cart page-updated", await c.get("/cart/", params={"distance_km": "18"}))
        rec.response("checkout no-vehicle", await c.post("/cart/checkout/", data=order))
        rec.response("checkout small", await c.post("/cart/checkout/", data={**order, "vehicle_id": truck}))
        bad_inn = {**order, "vehicle_id": long_, **company, "inn": "1"}
        rec.response("checkout bad-inn", await c.post("/cart/checkout/", data=bad_inn))
        done = {**order, "vehicle_id": long_, **company, "name": "Иван", "payment": "invoice", "comment": "звонить"}
        rec.response("checkout done", await c.post("/cart/checkout/", data=done))
        rec.response("cart after-order", await c.get("/cart/"))
    async with site_client() as c:
        await c.post("/cart/add/", data={**bad, "qty": "11,7"})
        await c.post("/cart/remove/", data={"index": 0})
        rec.response("cart removed", await c.get("/cart/"))
        await c.post("/cart/add/", data={**bad, "qty": "11,7"})
        pickup = {"phone": "+79160000000", "delivery": "pickup"}
        rec.response("checkout pickup", await c.post("/cart/checkout/", data=pickup))
        rec.response("checkout bot", await c.post("/cart/checkout/", data={**pickup, "website": "x"}))


ADMIN_VIEWS = ["category", "product", "price", "filter-landing", "redirect", "lead", "delivery-vehicle"]
TABLES = [
    ("categories", "id, parent_id, slug, path, name, sort, is_active, title, h1"),
    ("products", "id, category_id, slug, path, name, is_active, in_stock, search_text, attrs::text"),
    ("prices", "product_id, unit, amount_kop"),
    ("filter_landings", "id, category_id, slug, path, name, is_generated, is_indexable"),
    ("redirects", "from_path, to_path, status_code"),
    ("leads", "id, product_id, product_name, name, phone, comment, status, calc::text"),
]


async def record_admin_pages(rec: Recorder, admin, tag: str) -> None:
    for view in ADMIN_VIEWS:
        r = await admin.get(f"/admin/{view}/list")
        rec.response(f"admin {tag} {view}/list", r)
        for pk in sorted(set(re.findall(rf"/admin/{view}/details/(\d+)", r.text)), key=int)[:6]:
            for kind in ("details", "edit"):
                rec.response(f"admin {tag} {view}/{kind}/{pk}", await admin.get(f"/admin/{view}/{kind}/{pk}"))
        rec.response(f"admin {tag} {view}/create", await admin.get(f"/admin/{view}/create"))
    rec.response(f"admin {tag} index", await admin.get("/admin/"))


async def record_tables(rec: Recorder) -> None:
    from sqlalchemy import text

    from app.core.db import SessionLocal

    async with SessionLocal() as s:
        for table, columns in TABLES:
            sql = text(f"SELECT {columns} FROM {table} ORDER BY 1, 2")  # noqa: S608 — свои константы
            rows = [[str(v) for v in row] for row in (await s.execute(sql)).all()]
            rec.add(f"db {table}", 200, "", "\n".join(json.dumps(row, ensure_ascii=False) for row in rows))


async def record_admin(rec: Recorder) -> None:
    """Страницы всех разделов админки, сохранения через формы, затем таблицы и страницы после них."""
    from sqlalchemy import select

    from app.catalog.models import Category, FilterLanding, Product
    from app.core.db import SessionLocal
    from app.leads.models import Lead

    async with site_client() as admin:
        login = await admin.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
        if login.status_code != 302:
            raise SystemExit("Не удалось войти в админку для снимка")
        await record_admin_pages(rec, admin, "before")
        async with SessionLocal() as s:
            pipe = await s.scalar(select(Category).where(Category.path == "truba-profilnaya/kvadratnaya"))
            product = await s.scalar(
                select(Product).where(Product.path == "truba-profilnaya/kvadratnaya/40x40/40x40x2")
            )
            landing = await s.scalar(
                select(FilterLanding).where(FilterLanding.path == "truba-profilnaya/kvadratnaya/40x40")
            )
            lead = Lead(product_name="Снимок", phone="+79160000000", calc={"total_kop": 100})
            s.add(lead)
            await s.commit()
        if not (pipe and product and landing):
            raise SystemExit("В демо-каталоге нет квадратной трубы 40х40х2 — поправьте пути в scripts/snapshot.py")

        async def post(name: str, url: str, data: dict) -> None:
            rec.response(f"admin save {name}", await admin.post(url, data=data))

        cat = {"name": "Квадратная", "slug": "kvadratnaya", "sort": "0", "is_active": "y"}
        await post("category-into-itself", f"/admin/category/edit/{pipe.id}", {**cat, "parent": str(pipe.id)})
        renamed = {**cat, "name": "Квадратная труба", "slug": "kvadratnaya-truba", "parent": str(pipe.parent_id)}
        await post("category-rename", f"/admin/category/edit/{pipe.id}", renamed)
        async with SessionLocal() as s:
            category_id = (await s.get(Product, product.id)).category_id
        form = {
            "name": product.name,
            "slug": product.slug,
            "category": str(category_id),
            "base_unit": "m",
            "attrs": "{}",
            "in_stock": "y",
            "is_active": "y",
            "width_mm": "40",
            "height_mm": "40",
            "thickness_mm": "2",
            "length_m": "6",
            "weight_per_m_kg": "2.31",
        }
        edit = f"/admin/product/edit/{product.id}"
        await post("product-bad-price", edit, {**form, "price_m": "сорок"})
        await post("product-price", edit, {**form, "price_m": "123,45", "price_t": ""})
        await post("product-rename", edit, {**form, "name": "Труба 40х40х2 новая", "slug": "", "price_m": "123,45"})
        new = {**form, "name": "Труба снимок 10х10х1", "slug": "", "price_m": "10", "price_t": "20 000"}
        await post("product-create", "/admin/product/create", new)
        landing_form = {
            "name": landing.name,
            "slug": "40x40-ruchnaya",
            "category": str(landing.category_id),
            "filters": json.dumps(landing.filters),
            "is_indexable": "y",
            "sort": "0",
        }
        await post("landing-edit", f"/admin/filter-landing/edit/{landing.id}", landing_form)
        redirect = {"from_path": "Snap-Old", "to_path": "catalog/armatura", "status_code": "301"}
        await post("redirect-create", "/admin/redirect/create", redirect)
        await post("lead-status", f"/admin/lead/edit/{lead.id}", {"status": "done", "comment": "снимок"})
        await record_tables(rec)
        await record_admin_pages(rec, admin, "after")


async def record_all() -> list[Entry]:
    rec = Recorder()
    await record_site(rec)
    await record_leads(rec)
    await record_cart(rec)
    await record_admin(rec)
    from app.core.db import engine

    await engine.dispose()
    return rec.entries


def take(name: str) -> list[Entry]:
    print(f"Снимок «{name}»: база {SNAPSHOT_DB} с демо-каталогом…", flush=True)
    address = prepare_database()
    from app.core.config import settings

    # До первого импорта app.core.db: движок базы создаётся по этому адресу
    settings.database_url = address
    settings.admin_username, settings.admin_password = ADMIN_USER, ADMIN_PASSWORD
    import app.main  # noqa: F401 — настраивает логи приложения, их глушим ниже

    logging.disable(logging.ERROR)  # ошибки форм админка пишет в лог с трассировкой — в отчёте они лишние
    print("Обхожу сайт, заявки, корзину и админку…", flush=True)
    entries = asyncio.run(record_all())
    save(entries, SNAPSHOTS_DIR / name)
    print(f"Сохранено {len(entries)} ответов в {SNAPSHOTS_DIR / name}", flush=True)
    return entries


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "before":
        take("before")
        return 0
    if command == "diff":
        if not (SNAPSHOTS_DIR / "before" / "index.json").exists():
            print("Нет снимка «до»: сначала make snapshot (на коде до изменений)")
            return 2
        before = load(SNAPSHOTS_DIR / "before")
        after = take("after")
        diff = compare(before, after)
        print("\n".join(diff.report(before, after)))
        return 1 if (diff.changed or diff.missing or diff.added) else 0
    print("Использование: python -m scripts.snapshot before | diff")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
