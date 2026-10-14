import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.catalog import repository as repo
from app.catalog.router import router as catalog_router
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.nav import NavMiddleware
from app.core.templating import TEMPLATES_DIR, templates
from app.leads.router import router as leads_router
from app.pages.router import router as pages_router
from app.seo.meta import PageMeta, absolute
from app.seo.middleware import CanonicalUrlMiddleware
from app.seo.router import router as seo_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(
        title=settings.site_name,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
    )
    app.add_middleware(NavMiddleware)
    app.add_middleware(CanonicalUrlMiddleware)
    app.mount("/static", StaticFiles(directory=str(TEMPLATES_DIR.parent / "static")), name="static")

    app.include_router(pages_router)
    app.include_router(catalog_router)
    app.include_router(seo_router)
    app.include_router(leads_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            # Старые адреса из таблицы редиректов (меняются в админке без деплоя)
            async with SessionLocal() as session:
                redirect = await repo.get_redirect(session, request.url.path)
            if redirect:
                return RedirectResponse(redirect.to_path, status_code=redirect.status_code)
            meta = PageMeta(
                title=f"Страница не найдена | {settings.site_name}",
                description="",
                h1="Страница не найдена",
                canonical=absolute(request.url.path),
                robots="noindex, follow",
            )
            return templates.TemplateResponse(request, "404.html", {"meta": meta}, status_code=404)
        return HTMLResponse(str(exc.detail), status_code=exc.status_code)

    return app


app = create_app()
