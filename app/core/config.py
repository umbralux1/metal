import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Тестовые настройки для Render: файл в репозитории, подключается только когда приложение работает на Render.
RENDER_ENV_FILE = PROJECT_ROOT / "deploy" / "render.env"


def env_files() -> tuple[str | Path, ...]:
    """Локально — .env. На Render (там задана переменная RENDER) — ещё и deploy/render.env.

    Порядок важности: переменные окружения (панель Render) > deploy/render.env > .env > значения в коде.
    """
    return (".env", RENDER_ENV_FILE) if os.environ.get("RENDER") else (".env",)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _unique(items: list[str]) -> list[str]:
    return [item for i, item in enumerate(items) if item and item not in items[:i]]


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения и файлов из env_files()."""

    model_config = SettingsConfigDict(env_file=env_files(), env_file_encoding="utf-8", extra="ignore")

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
    work_hours: str = "Пн–Сб 9:00–19:00, Вс 10:00–15:00"  # формат важен: из него же часы в разметке (app/seo/hours.py)
    address: str = ""  # адрес склада для подвала и контактов; пусто — не показываем
    whatsapp: str = ""  # номер цифрами, например 79160000000; пусто — кнопки нет
    telegram: str = ""  # имя пользователя или бота без @
    # Список контактов в шапке (стрелка у телефона) и на /contacts/. Через запятую; пусто — только основной.
    extra_phones: str = ""
    extra_emails: str = ""
    # У MAX нет ссылки по номеру, как wa.me: ссылку копируют в приложении (профиль → «Поделиться»).
    # Целиком: https://max.ru/u/… (профиль) или https://max.ru/@имя (бот). Пусто — кнопки нет.
    max_url: str = ""

    # Яндекс Карта на странице /contacts/. Координаты склада — из Яндекс Карт (клик по точке → «55.75, 37.62»).
    # Пусто — показываем карту города без метки.
    map_lat: float | None = None
    map_lon: float | None = None
    map_zoom: int = 16

    # false — сайт закрыт от поисковиков: robots.txt «Disallow: /» и заголовок X-Robots-Tag.
    # Для тестовых копий (Render до подключения домена), чтобы они не попали в индекс.
    allow_indexing: bool = True
    # true — при запуске на хостинге загрузить демо-товары в пустую базу (python main.py)
    seed_demo: bool = False
    # true — при запуске на хостинге обновить посадочные «по размеру» из каталога (app/catalog/landings.py)
    auto_landings: bool = True

    page_size: int = 24

    # Админка на /admin. Пустой пароль — админка выключена.
    admin_username: str = "admin"
    admin_password: str = ""
    # Ключ для подписи сессии админки. Если не задан, генерируется при запуске (сессии сбросятся после рестарта).
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # Калькулятор: цена одного реза и с какого веса действует цена за тонну
    cut_price_kop: int = 5000
    ton_price_from_kg: int = 1000

    @property
    def phones(self) -> list[str]:
        """Основной телефон первым, затем дополнительные (без повторов)."""
        return _unique([self.phone, *_split(self.extra_phones)])

    @property
    def emails(self) -> list[str]:
        return _unique([self.email, *_split(self.extra_emails)])

    @property
    def messengers(self) -> list[tuple[str, str, str]]:
        """(вид, название, ссылка) для заполненных мессенджеров — в порядке показа."""
        items = []
        if tg := self.telegram.strip().removeprefix("https://t.me/").removeprefix("@").strip("/"):
            items.append(("telegram", "Telegram", f"https://t.me/{tg}"))
        if wa := "".join(ch for ch in self.whatsapp if ch.isdigit()):
            items.append(("whatsapp", "WhatsApp", f"https://wa.me/{wa}"))
        if self.max_url.strip().startswith("https://max.ru/"):
            items.append(("max", "MAX", self.max_url.strip()))
        return items

    @field_validator("map_lat", "map_lon", mode="before")
    @classmethod
    def _empty_coordinate(cls, value: object) -> object:
        return None if value == "" else value

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
