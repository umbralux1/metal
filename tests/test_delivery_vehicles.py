"""Подзадача 1 доставки: таблица машин и начальные тарифы.

Что договорились реализовать (тесты описывают это поведение):
- модель app.delivery.models.DeliveryVehicle, таблица delivery_vehicles, миграция 0004;
- деньги в копейках (как цены товаров), длина в метрах, грузоподъёмность в килограммах;
- app.delivery.seed: DEFAULT_VEHICLES и seed_vehicles(session) — кладёт начальные тарифы только в пустую
  таблицу, поэтому правки из админки и удалённые машины не возвращаются при перезапуске;
- prepare_database при каждом запуске вызывает app.delivery.seed.main (тарифы нужны и в продакшене,
  не только с демо-каталогом).

Модули доставки импортируются внутри тестов: пока их нет, падают только эти тесты, а не весь набор.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import SessionLocal
from tests.helpers import run_alembic

# Тарифы из ТЗ: (название, грузоподъёмность кг, длина м, базовая цена ₽, км в базовой цене, ₽ за км сверх, выгрузка сами)
TARIFFS = [
    ("Грузовик до 1,2 т", 1200, Decimal("3"), 1850, 5, 130, True),
    ("Грузовик до 5 т", 5000, Decimal("6"), 2400, 10, 150, True),
    ("Манипулятор до 10 т", 10000, Decimal("8"), 15000, 25, 190, False),
    ("Длинномер до 25 т", 25000, Decimal("13.5"), 18500, 30, 180, True),
]


def _as_tuple(v) -> tuple:
    return (
        v.name,
        v.max_weight_kg,
        Decimal(v.max_length_m),
        v.base_price_kop // 100,
        v.included_km,
        v.price_per_km_kop // 100,
        v.self_unloading,
    )


@pytest_asyncio.fixture
async def empty_vehicles():
    """Пустая таблица машин на время теста; после — снова начальные тарифы для остальных тестов."""
    from app.delivery.models import DeliveryVehicle
    from app.delivery.seed import seed_vehicles

    async with SessionLocal() as session:
        await session.execute(delete(DeliveryVehicle))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(DeliveryVehicle))
        await session.commit()
        await seed_vehicles(session)


async def _vehicles(session):
    from app.delivery.models import DeliveryVehicle

    return list(await session.scalars(select(DeliveryVehicle).order_by(DeliveryVehicle.sort)))


# ---------- Начальные тарифы ----------


def test_default_tariffs_match_spec():
    from app.delivery.seed import DEFAULT_VEHICLES

    rows = [
        (
            v["name"],
            v["max_weight_kg"],
            Decimal(str(v["max_length_m"])),
            v["base_price_kop"] // 100,
            v["included_km"],
            v["price_per_km_kop"] // 100,
            v["self_unloading"],
        )
        for v in DEFAULT_VEHICLES
    ]
    assert rows == TARIFFS
    # Копейки — целые и кратны рублю: в тарифах нет копеек
    assert all(v["base_price_kop"] % 100 == 0 and v["price_per_km_kop"] % 100 == 0 for v in DEFAULT_VEHICLES)


async def test_seed_fills_empty_table_in_order(empty_vehicles):
    from app.delivery.seed import seed_vehicles

    async with SessionLocal() as session:
        assert await seed_vehicles(session) == 4
        vehicles = await _vehicles(session)
    assert [_as_tuple(v) for v in vehicles] == TARIFFS  # от маленькой машины к большой, как в карточках
    assert all(v.is_active for v in vehicles)


async def test_seed_twice_does_not_duplicate(empty_vehicles):
    from app.delivery.seed import seed_vehicles

    async with SessionLocal() as session:
        await seed_vehicles(session)
        assert await seed_vehicles(session) == 0  # перезапуск сервера на Render
        assert len(await _vehicles(session)) == 4


async def test_seed_keeps_admin_edits_and_deletions(empty_vehicles):
    from app.delivery.models import DeliveryVehicle
    from app.delivery.seed import seed_vehicles

    async with SessionLocal() as session:
        await seed_vehicles(session)
        small, *_ = await _vehicles(session)
        small.base_price_kop = 199_000  # подняли цену в админке
        await session.execute(delete(DeliveryVehicle).where(DeliveryVehicle.name == "Манипулятор до 10 т"))
        await session.commit()

        assert await seed_vehicles(session) == 0
        names = {v.name: v for v in await _vehicles(session)}
    assert names["Грузовик до 1,2 т"].base_price_kop == 199_000
    assert "Манипулятор до 10 т" not in names  # удалённая машина не воскресает


# ---------- Защита данных на уровне базы ----------


@pytest.mark.parametrize(
    "bad",
    [
        {"max_weight_kg": 0},
        {"max_length_m": Decimal("0")},
        {"base_price_kop": -100},
        {"price_per_km_kop": -1},
        {"included_km": -5},
    ],
    ids=["zero-weight", "zero-length", "negative-price", "negative-km-price", "negative-km"],
)
async def test_db_rejects_invalid_vehicle(empty_vehicles, bad):
    from app.delivery.models import DeliveryVehicle

    data = {
        "name": "Проверка",
        "max_weight_kg": 1000,
        "max_length_m": Decimal("6"),
        "base_price_kop": 100_000,
        "included_km": 10,
        "price_per_km_kop": 10_000,
    } | bad
    async with SessionLocal() as session:
        session.add(DeliveryVehicle(**data))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_vehicle_names_are_unique(empty_vehicles):
    from app.delivery.models import DeliveryVehicle
    from app.delivery.seed import seed_vehicles

    async with SessionLocal() as session:
        await seed_vehicles(session)
        session.add(
            DeliveryVehicle(
                name="Грузовик до 5 т",
                max_weight_kg=5000,
                max_length_m=Decimal("6"),
                base_price_kop=1,
                included_km=1,
                price_per_km_kop=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


# ---------- Запуск сервера ----------


def test_startup_seeds_vehicles_even_without_demo(monkeypatch):
    import app.core.startup as startup

    called = []

    async def fake_main():
        called.append(True)

    monkeypatch.setattr(startup, "migrate", lambda: None)
    monkeypatch.setattr(settings, "seed_demo", False)
    monkeypatch.setattr(settings, "auto_landings", False)
    monkeypatch.setattr("app.delivery.seed.main", fake_main)
    startup.prepare_database()
    assert called == [True]


# ---------- Миграции ----------


def test_migrations_match_models(migrations_db):
    """База из миграций совпадает с моделями: поймает и забытую миграцию, и миграцию с ошибкой."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    run_alembic("upgrade", "head")
    with migrations_db.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    migrations_db.dispose()
    assert diff == [], f"Модели и миграции расходятся — нужна миграция: {diff}"


def test_delivery_migration_upgrades_and_downgrades(migrations_db):
    run_alembic("upgrade", "head")
    columns = {c["name"] for c in inspect(migrations_db).get_columns("delivery_vehicles")}
    assert {
        "name",
        "max_weight_kg",
        "max_length_m",
        "base_price_kop",
        "included_km",
        "price_per_km_kop",
        "self_unloading",
        "sort",
        "is_active",
    } <= columns
    assert inspect(migrations_db).get_check_constraints("delivery_vehicles"), "нет проверок в базе"

    run_alembic("downgrade", "0003")  # откат на версию до доставки
    migrations_db.dispose()
    assert "delivery_vehicles" not in inspect(migrations_db).get_table_names()

    run_alembic("upgrade", "head")  # и обратно — миграция повторяема
    migrations_db.dispose()
    assert "delivery_vehicles" in inspect(migrations_db).get_table_names()
    migrations_db.dispose()
