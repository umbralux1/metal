from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.static import static_url

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def format_rub(kop: int | None) -> str:
    """4325 → «43,25 ₽», 4870000 → «48 700 ₽» (с неразрывными пробелами)."""
    if kop is None:
        return ""
    rub, rest = divmod(int(kop), 100)
    whole = f"{rub:,}".replace(",", " ")
    return f"{whole},{rest:02d} ₽" if rest else f"{whole} ₽"


def format_decimal(value) -> str:
    """Decimal, int или float → «11,7», «1», «0,888»."""
    if value is None:
        return ""
    from decimal import Decimal

    return f"{Decimal(str(value)).normalize():f}".replace(".", ",")


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["rub"] = format_rub
templates.env.filters["num"] = format_decimal
templates.env.globals["settings"] = settings


def _phone_href(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return f"tel:{digits}"


def _register_drawings() -> None:
    # Импорт здесь, чтобы не было циклической зависимости модели ↔ шаблоны
    from app.catalog.drawings import category_icon, hero_svg, section_svg

    templates.env.globals["section_svg"] = section_svg
    templates.env.globals["category_icon"] = category_icon
    templates.env.globals["hero_svg"] = hero_svg


templates.env.globals["phone_href"] = _phone_href
templates.env.globals["static_url"] = static_url
templates.env.globals["current_year"] = lambda: date.today().year
_register_drawings()
