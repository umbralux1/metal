"""Точка входа: `python main.py`.

Перед стартом — и локально, и на хостинге: миграции, демо-данные при SEED_DEMO=true,
посадочные и адреса товаров (AUTO_LANDINGS=true). Так локальная база всегда в том же виде, что на Render.

Локально — сервер для разработки на 127.0.0.1:8000 с автоперезагрузкой.
На хостинге (задана переменная PORT, как на Render) — запуск на 0.0.0.0:$PORT без автоперезагрузки.
"""

import os


def server_options(env: dict[str, str]) -> dict:
    on_host = "PORT" in env
    return {
        "host": "0.0.0.0" if on_host else "127.0.0.1",  # noqa: S104 — на Render слушать все интерфейсы обязательно
        "port": int(env.get("PORT", 8000)),
        "reload": not on_host,
        "proxy_headers": True,
        "forwarded_allow_ips": "*" if on_host else "127.0.0.1",
    }


def check_host_env(env: dict[str, str], secret_key_set: bool | None = None) -> None:
    """На хостинге без SECRET_KEY не запускаться: иначе у каждой копии свой случайный ключ — расходятся отпечатки
    адресов в счёте заявок (specs/001-lead-rate-limit) и сессии админки. Ключ может быть и в файле настроек —
    тогда его наличие передаёт вызывающий (secret_key_set)."""
    if secret_key_set is None:
        secret_key_set = bool(env.get("SECRET_KEY"))
    if "PORT" in env and not secret_key_set:
        raise SystemExit("Не задан SECRET_KEY: на хостинге он обязателен и одинаков у всех копий сайта")


if __name__ == "__main__":
    import uvicorn

    from app.bootstrap import prepare_database
    from app.core.config import settings

    # Ключ задан, если пришёл из окружения или файла настроек, а не придуман при запуске (config.py)
    check_host_env(dict(os.environ), "secret_key" in settings.model_fields_set)
    options = server_options(dict(os.environ))
    # Один раз в основном процессе: при автоперезагрузке код перезапускается без повторных миграций
    prepare_database()
    uvicorn.run("app.main:app", **options)
