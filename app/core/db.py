from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

# Предсказуемые имена индексов и ограничений: Alembic генерирует стабильные миграции
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# connect_timeout — база недоступна: ошибка через 10 с, а не вечное ожидание.
# idle_in_transaction_session_timeout — забытая открытая транзакция не держит блокировки таблиц
# (иначе миграция при деплое ждёт её бесконечно).
CONNECT_ARGS = {"connect_timeout": 10, "options": "-c idle_in_transaction_session_timeout=60000"}

engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args=CONNECT_ARGS)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
