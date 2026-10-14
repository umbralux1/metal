"""Статика с отпечатком версии: /static/css/main.css?v=3f9a1c2b4d.

Отпечаток — хэш содержимого файла. Файл изменился → адрес изменился → браузер скачивает новую версию
сам, чистить кэш не нужно. Пока файл тот же, браузер держит его в кэше год и не спрашивает сервер.
Адрес без ?v= (например, шрифт из CSS) браузер каждый раз сверяет с сервером: если файл не менялся,
сервер отвечает коротким 304 без тела.
"""

import hashlib
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LONG_CACHE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

_hashes: dict[str, tuple[float, str]] = {}


def file_hash(path: str) -> str:
    """Хэш файла из app/static; пересчитывается, только когда файл изменился (по времени изменения)."""
    full = STATIC_DIR / path
    mtime = full.stat().st_mtime
    cached = _hashes.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    digest = hashlib.md5(full.read_bytes(), usedforsecurity=False).hexdigest()[:10]
    _hashes[path] = (mtime, digest)
    return digest


def static_url(path: str) -> str:
    """Для шаблонов: {{ static_url('css/main.css') }} → /static/css/main.css?v=3f9a1c2b4d."""
    path = path.lstrip("/")
    try:
        return f"/static/{path}?v={file_hash(path)}"
    except FileNotFoundError:
        return f"/static/{path}"


class VersionedStaticFiles(StaticFiles):
    """Заголовки кэша: с ?v= — на год, без версии — сверяться с сервером при каждом открытии."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            versioned = b"v=" in (scope.get("query_string") or b"")
            response.headers["Cache-Control"] = LONG_CACHE if versioned else REVALIDATE
        return response
