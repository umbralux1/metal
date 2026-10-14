from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.config import settings

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def format_rub(kop: int | None) -> str:
    """4325 → «43,25 ₽», 4870000 → «48 700 ₽» (с неразрывными пробелами)."""
    if kop is None:
        return ""
    rub, rest = divmod(int(kop), 100)
    whole = f"{rub:,}".replace(",", " ")
    return f"{whole},{rest:02d} ₽" if rest else f"{whole} ₽"


def format_decimal(value) -> str:
    if value is None:
        return ""
    return f"{value.normalize():f}".replace(".", ",")


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["rub"] = format_rub
templates.env.filters["num"] = format_decimal
templates.env.globals["settings"] = settings
