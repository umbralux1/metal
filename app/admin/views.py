"""Подключение админки: все разделы в одном месте. Сами разделы — в файлах по предметным областям."""

from fastapi import FastAPI
from sqladmin import Admin

from app.admin.auth import AdminAuth
from app.admin.catalog import CategoryAdmin, FilterLandingAdmin, PriceAdmin, ProductAdmin
from app.admin.delivery import DeliveryVehicleAdmin
from app.admin.leads import LeadAdmin
from app.admin.redirects import RedirectAdmin
from app.core.config import settings
from app.core.db import SessionLocal, engine


def setup_admin(app: FastAPI) -> Admin | None:
    """Подключает /admin, если задан пароль. Без пароля админки нет совсем."""
    if not settings.admin_password:
        return None
    auth = AdminAuth()
    admin = Admin(
        app,
        engine=engine,
        session_maker=SessionLocal,
        authentication_backend=auth,
        title=f"{settings.site_name} — админка",
        base_url="/admin",
    )
    auth.templates = admin.templates  # страница входа с ошибкой 429 — шаблоном SQLAdmin
    for view in (
        CategoryAdmin,
        ProductAdmin,
        PriceAdmin,
        FilterLandingAdmin,
        RedirectAdmin,
        LeadAdmin,
        DeliveryVehicleAdmin,
    ):
        admin.add_view(view)
    return admin
