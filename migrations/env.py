import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.db import CONNECT_ARGS
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Сколько миграция ждёт блокировку таблицы. Дольше — ошибка и повтор (app/core/startup.py), а не вечное ожидание.
LOCK_TIMEOUT = "15s"


def do_run_migrations(connection: Connection) -> None:
    connection.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    # Транзакции, которые больше 5 с открыты и ничего не делают (например, у старой версии сайта во время деплоя),
    # держат блокировки и не дают изменить таблицу. Их снимаем — работающие запросы не трогаем.
    connection.exec_driver_sql(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid() "
        "AND state IN ('idle in transaction', 'idle in transaction (aborted)') "
        "AND state_change < now() - interval '5 seconds'"
    )
    # Зафиксировать служебные команды: иначе Alembic сочтёт открытую транзакцию чужой и не закоммитит миграцию.
    # lock_timeout задан на сессию и после коммита продолжает действовать.
    connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, connect_args=CONNECT_ARGS)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
