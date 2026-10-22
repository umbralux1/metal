import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.calculator import CalcError, calculate, parse_input
from app.catalog.models import Product
from app.core.config import settings
from app.core.db import get_session
from app.core.templating import templates
from app.leads.models import Lead
from app.leads.notify import notify_new_lead
from app.seo.meta import PageMeta, absolute

router = APIRouter()


def normalize_phone(raw: str) -> str | None:
    """«8 (916) 123-45-67» → «+79161234567». None, если номер не похож на российский."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    return None


def _is_fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


@router.post("/api/lead/", response_class=HTMLResponse, include_in_schema=False)
async def create_lead(request: Request, session: AsyncSession = Depends(get_session)):
    raw = await request.form()
    if not all(isinstance(value, str) for value in raw.values()):  # файл вместо текста — так шлют только боты
        return HTMLResponse("Неверные данные формы", status_code=422)
    form = {key: value for key, value in raw.items() if isinstance(value, str)}
    product = await session.scalar(select(Product).where(Product.id == _int(form.get("product_id"))))
    values = {k: str(form.get(k, "")).strip() for k in ("name", "phone", "comment")}

    def form_error(message: str, status: int = 422):
        context = {"product": product, "params": form, "values": values, "error": message}
        return templates.TemplateResponse(request, "leads/_form.html", context, status_code=status)

    if form.get("website"):  # поле-ловушка для ботов, люди его не видят
        return templates.TemplateResponse(request, "leads/_done.html", {"lead": None})
    if product is None:
        return form_error("Товар не найден, обновите страницу", status=404)
    phone = normalize_phone(values["phone"])
    if phone is None:
        return form_error("Проверьте номер телефона: нужен российский номер, например +7 916 123-45-67")
    try:
        result = calculate(product, parse_input(form, product), settings.cut_price_kop, settings.ton_price_from_kg)
    except CalcError as exc:
        return form_error(str(exc))

    calc = result.as_dict() | {
        "unit": form.get("unit"),
        "qty": form.get("qty"),
        "cut": bool(form.get("cut")),
        "cut_len": form.get("cut_len"),
        "cut_count": form.get("cut_count"),
    }
    lead = Lead(
        product_id=product.id,
        product_name=product.name,
        name=values["name"][:120],
        phone=phone,
        comment=values["comment"][:2000],
        calc=calc,
    )
    session.add(lead)
    await session.commit()
    await notify_new_lead(lead)

    if _is_fetch(request):
        return templates.TemplateResponse(request, "leads/_done.html", {"lead": lead})
    meta = PageMeta(
        title=f"Заявка принята | {settings.site_name}",
        description="",
        h1="Заявка принята",
        canonical=absolute("/"),
        robots="noindex, nofollow",
    )
    return templates.TemplateResponse(request, "leads/done_page.html", {"meta": meta, "lead": lead, "product": product})


def _int(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0
