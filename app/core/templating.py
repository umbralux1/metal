from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def format_local_time(moment: datetime | None) -> str:
    """Время из базы → «15.01.2030 01:30» в часовом поясе сайта (TIMEZONE)."""
    if moment is None:
        return ""
    return moment.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y %H:%M")


def site_year(moment: datetime) -> int:
    """Год в часовом поясе сайта (TIMEZONE): в новогоднюю ночь по UTC ещё старый год, а по Москве уже новый."""
    return moment.astimezone(ZoneInfo(settings.timezone)).year


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


templates.env.globals["phone_href"] = _phone_href
templates.env.globals["static_url"] = static_url


templates.env.globals["current_year"] = lambda: site_year(datetime.now(UTC))
