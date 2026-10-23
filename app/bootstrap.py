"""Подготовка базы перед запуском сервера на хостинге: миграции, демо-данные, посадочные.

Каждый шаг пишется в лог сразу (со временем), чтобы в логах Render было видно, где идёт работа.
Миграция не может зависнуть: ожидание блокировки ограничено (migrations/env.py), при неудаче — повторы,
после них — понятная ошибка, и Render оставляет работать предыдущую версию сайта.
"""

import asyncio
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

MIGRATION_ATTEMPTS = 5
RETRY_PAUSE_S = 5


def step(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def migrate(attempts: int = MIGRATION_ATTEMPTS, pause: float = RETRY_PAUSE_S) -> None:
    for attempt in range(1, attempts + 1):
        try:
            command.upgrade(Config("alembic.ini"), "head")
            return
        except OperationalError as exc:  # не дождались блокировки или нет связи с базой
            reason = str(getattr(exc, "orig", exc)).strip().splitlines()[0][:160]
            if attempt == attempts:
                raise RuntimeError(
                    f"Миграция не выполнена после {attempts} попыток: {reason}. "
                    "Если база недоступна — проверьте DATABASE_URL и что база запущена; "
                    "если таблицы заняты — перезапустите деплой."
                ) from exc
            step(f"Миграция не удалась, попытка {attempt} из {attempts}: {reason}")
            time.sleep(pause)


def prepare_database() -> None:
    from app.core.config import settings

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # логи сразу, а не пачкой в конце
    started = time.monotonic()
    step("Подготовка базы: миграции…")
    migrate()
    # Тарифы доставки нужны и на боевом сайте, не только с демо-каталогом. В непустую таблицу не пишет.
    step("Подготовка базы: машины доставки…")
    from app.delivery.seed import main as seed_vehicles

    asyncio.run(seed_vehicles())
    if settings.seed_demo:
        step("Подготовка базы: демо-каталог…")
        from app.catalog.seed import main as seed

        asyncio.run(seed())
    if settings.auto_landings:
        step("Подготовка базы: посадочные и адреса товаров…")
        from app.catalog.landings import main as landings

        asyncio.run(landings())
    step(f"База готова за {time.monotonic() - started:.1f} с, запускаю сервер")
