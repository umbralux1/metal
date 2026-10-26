"""Чертежи сечений в SVG по размерам товара: штриховка разреза по ГОСТ 2.306, размерные линии.

Картинка строится из полей Product, поэтому есть у каждой позиции без фотографий.
Профиль берётся из attrs["profile"], иначе угадывается по заполненным размерам.
"""

from decimal import Decimal
from itertools import count

from markupsafe import Markup, escape

from app.catalog.models import Product
from app.core.numbers import format_decimal

INK = "#1b2630"
DIM = "#2b4acb"
HATCH = "#5b6b78"
RIBBED_GRADES = {"А500С", "А400", "А3", "A500C", "A400"}

_ids = count(1)


def profile_of(product: Product) -> str:
    explicit = (product.attrs or {}).get("profile")
    if explicit:
        return explicit
    if product.width_mm and product.height_mm and product.thickness_mm:
        return "tube_rect"
    if product.diameter_mm:
        return "rebar" if (product.steel_grade or "") in RIBBED_GRADES else "round"
    if product.thickness_mm:
        return "plate"
    return "unknown"


def _defs(uid: str) -> str:
    return (
        f'<defs><pattern id="h{uid}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{HATCH}" stroke-width="1.1"/></pattern>'
        f'<marker id="a{uid}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 1.5L10 5L0 8.5z" fill="{DIM}"/></marker>'
        "</defs>"
    )


def _hdim(x1: float, x2: float, y: float, ext_from: float, label: str, uid: str) -> str:
    """Горизонтальный размер: выносные линии от ext_from до y, размерная линия со стрелками, число над ней."""
    return (
        f'<g stroke="{DIM}" stroke-width="1">'
        f'<line x1="{x1}" y1="{ext_from}" x2="{x1}" y2="{y - 6}"/><line x1="{x2}" y1="{ext_from}" x2="{x2}" y2="{y - 6}"/>'
        f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" marker-start="url(#a{uid})" marker-end="url(#a{uid})"/></g>'
        f'<text x="{(x1 + x2) / 2}" y="{y - 8}" text-anchor="middle" class="dim">{escape(label)}</text>'
    )


def _vdim(y1: float, y2: float, x: float, ext_from: float, label: str, uid: str) -> str:
    return (
        f'<g stroke="{DIM}" stroke-width="1">'
        f'<line x1="{ext_from}" y1="{y1}" x2="{x + 6}" y2="{y1}"/><line x1="{ext_from}" y1="{y2}" x2="{x + 6}" y2="{y2}"/>'
        f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" marker-start="url(#a{uid})" marker-end="url(#a{uid})"/></g>'
        f'<text x="{x + 10}" y="{(y1 + y2) / 2 + 5}" class="dim">{escape(label)}</text>'
    )


def _rounded_rect(x: float, y: float, w: float, h: float, r: float) -> str:
    r = max(0.0, min(r, w / 2, h / 2))
    return (
        f"M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}V{y + h - r}"
        f"A{r} {r} 0 0 1 {x + w - r} {y + h}H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}V{y + r}"
        f"A{r} {r} 0 0 1 {x + r} {y}Z"
    )


def _tube_rect(width_mm: Decimal, height_mm: Decimal, thickness_mm: Decimal, uid: str) -> str:
    w, h, t = float(width_mm), float(height_mm), float(thickness_mm)
    box = 168
    scale = box / max(w, h)
    W, H = w * scale, h * scale
    tv = max(t * scale, 3.5)  # стенку рисуем не тоньше 3,5 px, иначе штриховки не видно
    x0, y0 = 72 + (box - W) / 2, 64 + (box - H) / 2
    outer = _rounded_rect(x0, y0, W, H, tv * 1.6)
    inner = _rounded_rect(x0 + tv, y0 + tv, W - 2 * tv, H - 2 * tv, tv * 0.6)
    lead_x, lead_y = x0 + W - tv / 2, y0 + H * 0.72
    return (
        f'<path d="{outer} {inner}" fill-rule="evenodd" fill="url(#h{uid})" stroke="{INK}" stroke-width="1.6"/>'
        + _hdim(x0, x0 + W, y0 - 22, y0 - 4, format_decimal(width_mm), uid)
        + _vdim(y0, y0 + H, x0 + W + 24, x0 + W + 4, format_decimal(height_mm), uid)
        + f'<g stroke="{DIM}" stroke-width="1" fill="none"><circle cx="{lead_x}" cy="{lead_y}" r="2" fill="{DIM}"/>'
        f'<polyline points="{lead_x},{lead_y} {x0 + W + 20},{y0 + H + 26} {x0 + W + 64},{y0 + H + 26}"/></g>'
        f'<text x="{x0 + W + 24}" y="{y0 + H + 21}" class="dim">t = {format_decimal(thickness_mm)}</text>'
    )


def _round(diameter_mm: Decimal, uid: str, ribbed: bool) -> str:
    cx, cy, r = 156, 156, 74
    ribs = ""
    if ribbed:
        # Два продольных ребра периодического профиля поверх круга
        ribs = "".join(
            f'<path d="M{cx + side * (r - 1)} {cy - 20}Q{cx + side * (r + 22)} {cy} {cx + side * (r - 1)} {cy + 20}Z" '
            f'fill="url(#h{uid})" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/>'
            for side in (-1, 1)
        )
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#h{uid})" stroke="{INK}" stroke-width="1.6"/>'
        + ribs
        + f'<g stroke="{INK}" stroke-width="0.8" stroke-dasharray="10 3 2 3">'
        f'<line x1="{cx - r - 28}" y1="{cy}" x2="{cx + r + 28}" y2="{cy}"/>'
        f'<line x1="{cx}" y1="{cy - r - 14}" x2="{cx}" y2="{cy + r + 14}"/></g>'
        + _hdim(cx - r, cx + r, cy - r - 28, cy - 6, f"Ø{format_decimal(diameter_mm)}", uid)
    )


def _plate(thickness_mm: Decimal, uid: str) -> str:
    t = float(thickness_mm)
    x0, y0, W = 50, 150, 220
    tv = max(min(t * 6, 60), 6)
    return (
        f'<rect x="{x0}" y="{y0}" width="{W}" height="{tv}" fill="url(#h{uid})" stroke="{INK}" stroke-width="1.6"/>'
        + _vdim(y0, y0 + tv, x0 + W + 30, x0 + W + 4, format_decimal(thickness_mm), uid)
    )


def section_svg(product: Product) -> Markup:
    """Крупный чертёж для карточки товара. Профиль не распознан или нужных размеров нет — пустая строка."""
    kind = profile_of(product)
    uid = str(next(_ids))
    w, h, t, d = product.width_mm, product.height_mm, product.thickness_mm, product.diameter_mm
    if kind == "tube_rect" and w and h and t:
        body = _tube_rect(w, h, t, uid)
    elif kind in ("rebar", "round") and d:
        body = _round(d, uid, ribbed=kind == "rebar")
    elif kind == "plate" and t:
        body = _plate(t, uid)
    else:
        return Markup("")
    label = f"Сечение: {product.name}, размеры в миллиметрах"
    return Markup(  # noqa: S704 — свой SVG из чисел, название экранировано
        f'<svg class="section-drawing" viewBox="0 0 360 300" role="img" aria-label="{escape(label)}" '
        f'xmlns="http://www.w3.org/2000/svg">{_defs(uid)}'
        f"{body}</svg>"
    )


def hero_svg() -> Markup:
    """Композиция для первого экрана: арматура и профильная труба в разрезе."""
    uid = str(next(_ids))
    return Markup(  # noqa: S704 — свой SVG из констант
        '<svg viewBox="0 0 440 340" role="img" aria-label="Чертежи сечений: арматура Ø12 и профильная труба 60×40×3" '
        f'xmlns="http://www.w3.org/2000/svg">{_defs(uid)}'
        f'<g transform="translate(-36 -6) scale(.78)">{_round(Decimal(12), uid, ribbed=True)}</g>'
        f'<g transform="translate(150 96) scale(.82)">{_tube_rect(Decimal(60), Decimal(40), Decimal(3), uid)}</g></svg>'
    )


def category_icon(slug: str) -> Markup:
    """Объёмный значок раздела (app/catalog/iso_icons.py)."""
    from app.catalog.iso_icons import iso_icon

    return iso_icon(slug)
