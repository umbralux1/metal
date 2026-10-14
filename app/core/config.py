from functools import lru_cache

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

    page_size: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
