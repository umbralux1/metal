"""Админка редиректов: адреса приводятся к виду /путь/ при сохранении."""

from typing import Any

from sqladmin import ModelView
from starlette.requests import Request

from app.admin.catalog import clean_text
from app.catalog.models import Redirect
from app.core.templating import format_local_time


class RedirectAdmin(ModelView, model=Redirect):
    name = "Редирект"
    name_plural = "Редиректы"
    icon = "fa-solid fa-route"
    category = "SEO"
    page_size = 100

    column_list = [Redirect.from_path, Redirect.to_path, Redirect.status_code, Redirect.created_at]
    column_labels = {"from_path": "Откуда", "to_path": "Куда", "status_code": "Код", "created_at": "Создан"}
    column_searchable_list = [Redirect.from_path, Redirect.to_path]
    column_default_sort = [(Redirect.created_at, True)]
    column_formatters = {Redirect.created_at: lambda m, a: format_local_time(m.created_at)}
    form_columns = [Redirect.from_path, Redirect.to_path, Redirect.status_code]
    form_args = {
        "from_path": {"description": "Старый адрес без домена, например /catalog/old-armatura/"},
        "to_path": {"description": "Новый адрес без домена, например /catalog/armatura/"},
        "status_code": {"description": "301 — переехало навсегда (обычно нужен он), 302 — временно"},
    }

    async def on_model_change(self, data: dict, model: Redirect, is_created: bool, request: Request) -> None:
        def norm(value: Any) -> str:
            value = "/" + clean_text(value).lstrip("/")
            last = value.rsplit("/", 1)[-1]
            return value if value.endswith("/") or "." in last else value + "/"

        data["from_path"] = norm(data.get("from_path")).lower()
        data["to_path"] = norm(data.get("to_path"))
        if data["from_path"] == data["to_path"]:
            raise ValueError("Адрес «откуда» совпадает с «куда»")
        if int(data.get("status_code") or 301) not in (301, 302, 308):
            raise ValueError("Код — 301, 302 или 308")
