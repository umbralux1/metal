"""Вход в админку по логину и паролю из настроек (ADMIN_USERNAME / ADMIN_PASSWORD).

Перебор паролей: после settings.admin_login_limit ошибок за settings.admin_login_limit_minutes вход с адреса закрыт.
Счёт — в базе, общий для всех копий сайта (specs/003-admin-login-limit).
"""

import logging
from hmac import compare_digest

from sqladmin.authentication import AuthenticationBackend
from sqladmin.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from starlette.requests import Request
from starlette.responses import Response

from app.admin.models import AdminLoginFailure
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.http import client_ip
from app.leads.fingerprint import client_fingerprint

logger = logging.getLogger("metal.admin")


class AdminAuth(AuthenticationBackend):
    # Шаблоны SQLAdmin для страницы входа с ошибкой 429; передаёт setup_admin после создания Admin
    templates: Jinja2Templates

    def __init__(self) -> None:
        super().__init__(secret_key=settings.secret_key)

    async def login(self, request: Request) -> Response | bool:
        fingerprint = client_fingerprint(client_ip(request), settings.secret_key)
        since = func.now() - func.make_interval(0, 0, 0, 0, 0, settings.admin_login_limit_minutes)  # по часам базы
        async with SessionLocal() as session:
            # Проверка и запись — под блокировкой по отпечатку: одновременные попытки с адреса не теряются.
            # Префикс отделяет её от блокировки заявок того же адреса
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext("admin-login:" + fingerprint))))
            await session.execute(delete(AdminLoginFailure).where(AdminLoginFailure.created_at <= since))
            recent = await session.scalar(
                select(func.count()).select_from(AdminLoginFailure).where(AdminLoginFailure.client_hash == fingerprint)
            )
            if (recent or 0) >= settings.admin_login_limit:
                await session.commit()
                logger.warning("Вход в админку закрыт для адреса %s", fingerprint)
                minutes = settings.admin_login_limit_minutes
                return await self.templates.TemplateResponse(
                    request,
                    "sqladmin/login.html",
                    {"error": f"Слишком много попыток, попробуйте через {minutes} минут"},
                    status_code=429,
                )
            form = await request.form()
            username = str(form.get("username", ""))
            password = str(form.get("password", ""))
            ok = compare_digest(username.encode(), settings.admin_username.encode()) and compare_digest(
                password.encode(), settings.admin_password.encode()
            )
            if ok:
                await session.execute(delete(AdminLoginFailure).where(AdminLoginFailure.client_hash == fingerprint))
            else:
                session.add(AdminLoginFailure(client_hash=fingerprint))
            await session.commit()
        if ok:
            request.session.update({"admin": True})
        return ok

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))
