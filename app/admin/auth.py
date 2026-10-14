"""Вход в админку по логину и паролю из настроек (ADMIN_USERNAME / ADMIN_PASSWORD)."""

import time
from hmac import compare_digest

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core.config import settings

MAX_FAILURES = 5
BLOCK_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent_failures(ip: str) -> list[float]:
    now = time.monotonic()
    recent = [t for t in _failures.get(ip, []) if now - t < BLOCK_SECONDS]
    _failures[ip] = recent
    return recent


def reset_login_limits() -> None:
    _failures.clear()


class AdminAuth(AuthenticationBackend):
    def __init__(self) -> None:
        super().__init__(secret_key=settings.secret_key)

    async def login(self, request: Request) -> bool:
        ip = _client_ip(request)
        # Перебор паролей: после 5 ошибок за 15 минут вход с этого адреса закрыт
        if len(_recent_failures(ip)) >= MAX_FAILURES:
            return False
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        ok = compare_digest(username.encode(), settings.admin_username.encode()) and compare_digest(
            password.encode(), settings.admin_password.encode()
        )
        if not ok:
            _failures.setdefault(ip, []).append(time.monotonic())
            return False
        _failures.pop(ip, None)
        request.session.update({"admin": True})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))
