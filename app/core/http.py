"""Общее для обработчиков запросов."""

from starlette.requests import Request


def client_ip(request: Request) -> str:
    """Адрес покупателя. За балансировщиком — из X-Forwarded-For (uvicorn с proxy_headers, main.py)."""
    return request.client.host if request.client else "unknown"
