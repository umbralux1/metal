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
        "host": "0.0.0.0" if on_host else "127.0.0.1",
        "port": int(env.get("PORT", 8000)),
        "reload": not on_host,
        "proxy_headers": True,
        "forwarded_allow_ips": "*" if on_host else "127.0.0.1",
    }


def prepare_database() -> None:
    """Перед стартом сервера: схема БД, демо-данные (по желанию), посадочные и адреса товаров."""
    import asyncio

    from alembic.config import main as alembic

    from app.core.config import settings

    alembic(argv=["upgrade", "head"])
    if settings.seed_demo:
        from app.catalog.seed import main as seed

        asyncio.run(seed())
    if settings.auto_landings:
        from app.catalog.landings import main as landings

        asyncio.run(landings())


if __name__ == "__main__":
    import uvicorn

    options = server_options(dict(os.environ))
    # Один раз в основном процессе: при автоперезагрузке код перезапускается без повторных миграций
    prepare_database()
    uvicorn.run("app.main:app", **options)
