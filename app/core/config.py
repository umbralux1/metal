import os
import secrets
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения и файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://metal:metal@localhost:5433/metal"
    debug: bool = False

    # Абсолютный адрес сайта без слеша в конце: из него строятся canonical, sitemap, JSON-LD
    site_url: str = "http://localhost:8000"
    site_name: str = "Металлобаза"
    city: str = "Москва"
    # Город в предложном/дательном падеже: «в Москве», «по Москве»
    city_prepositional: str = "Москве"
    phone: str = "+7 (495) 000-00-00"
    email: str = "info@example.ru"
    work_hours: str = "Пн–Сб 9:00–19:00, Вс 10:00–15:00"
    address: str = ""  # адрес склада для подвала и контактов; пусто — не показываем
    whatsapp: str = ""  # номер цифрами, например 79160000000; пусто — кнопки нет
    telegram: str = ""  # имя пользователя или бота без @

    # false — сайт закрыт от поисковиков: robots.txt «Disallow: /» и заголовок X-Robots-Tag.
    # Для тестовых копий (Render до подключения домена), чтобы они не попали в индекс.
    allow_indexing: bool = True

    page_size: int = 24

    # Админка на /admin. Пустой пароль — админка выключена.
    admin_username: str = "admin"
    admin_password: str = ""
    # Ключ для подписи сессии админки. Если не задан, генерируется при запуске (сессии сбросятся после рестарта).
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # Калькулятор: цена одного реза и с какого веса действует цена за тонну
    cut_price_kop: int = 5000
    ton_price_from_kg: int = 1000

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        """Render и другие хостинги отдают postgres:// или postgresql:// — нужен драйвер psycopg."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @model_validator(mode="after")
    def _require_database_on_render(self) -> "Settings":
        """На Render без DATABASE_URL приложение стучалось бы в localhost и отдавало 500 — лучше упасть сразу."""
        if os.environ.get("RENDER") and "database_url" not in self.model_fields_set:
            raise ValueError(
                "На Render не задана переменная DATABASE_URL. Создайте базу PostgreSQL (New → Postgres) "
                "и добавьте её Internal Database URL в Environment сервиса — или разверните проект через Blueprint."
            )
        return self

    @model_validator(mode="after")
    def _site_url_from_render(self) -> "Settings":
        """Если SITE_URL не задан, на Render берём его адрес вида https://metal-web.onrender.com."""
        if "site_url" not in self.model_fields_set and os.environ.get("RENDER_EXTERNAL_URL"):
            self.site_url = os.environ["RENDER_EXTERNAL_URL"]
        self.site_url = self.site_url.rstrip("/")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
