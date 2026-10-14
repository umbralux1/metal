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
    work_hours: str = "Пн–Сб 9:00–19:00, Вс 10:00–15:00"
    address: str = ""  # адрес склада для подвала и контактов; пусто — не показываем
    whatsapp: str = ""  # номер цифрами, например 79160000000; пусто — кнопки нет
    telegram: str = ""  # имя пользователя или бота без @

    page_size: int = 24

    # Калькулятор: цена одного реза и с какого веса действует цена за тонну
    cut_price_kop: int = 5000
    ton_price_from_kg: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
