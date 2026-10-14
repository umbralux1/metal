"""Объёмные значки разделов в линию: профиль металла, вытянутый вглубь (косоугольная проекция).

Каждый значок задаётся сечением — тем же, что видно на торце настоящего проката, — и длиной.
Грани рисуются от дальних к ближним с белой заливкой, поэтому невидимые линии перекрываются сами.
Результат кэшируется: SVG собирается один раз на значок.
"""

import math
from functools import lru_cache

from markupsafe import Markup

# Сдвиг на единицу глубины: прокат уходит вправо-вверх
SHIFT = (0.62, -0.42)
# Толщина линии в пикселях экрана — одинаковая для значка 24 px и 64 px
STROKE = 'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"'
FILL = "var(--icon-fill, #fff)"
HOLE = "var(--icon-hole, #e9edf0)"

Point = tuple[float, float]


def _p(u: float, v: float, t: float = 0.0) -> Point:
    """Точка сечения (u вправо, v вверх) на глубине t → координаты на экране (y вниз)."""
    return (u + t * SHIFT[0], -v + t * SHIFT[1])


def _poly(points: list[Point], fill: str = FILL, extra: str = "") -> str:
    d = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polygon points="{d}" fill="{fill}" {extra}/>'


def _line(a: Point, b: Point) -> str:
    return f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}"/>'


def _area(profile: list[Point]) -> float:
    return sum(u1 * v2 - u2 * v1 for (u1, v1), (u2, v2) in zip(profile, profile[1:] + profile[:1], strict=True)) / 2


class Icon:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.points: list[Point] = []

    def add(self, svg: str, *pts: Point) -> None:
        self.parts.append(svg)
        self.points.extend(pts)

    def prism(self, profile: list[Point], length: float, t0: float = 0.0, hole: list[Point] | None = None) -> None:
        """Сплошной профиль: задняя грань → видимые боковые грани (дальние раньше) → торец."""
        ccw = _area(profile) > 0
        back = [_p(u, v, t0 + length) for u, v in profile]
        front = [_p(u, v, t0) for u, v in profile]
        self.add(_poly(back), *back)
        sides = []
        n = len(profile)
        for i in range(n):
            (u1, v1), (u2, v2) = profile[i], profile[(i + 1) % n]
            # Внешняя нормаль ребра; грань видна, если смотрит туда же, куда уходит сдвиг (вверх-вправо)
            nu, nv = (v2 - v1, u1 - u2) if ccw else (v1 - v2, u2 - u1)
            if nu * SHIFT[0] - nv * SHIFT[1] <= 1e-9:
                continue
            depth = (u1 + u2) * SHIFT[0] - (v1 + v2) * SHIFT[1]
            quad = [front[i], front[(i + 1) % n], back[(i + 1) % n], back[i]]
            sides.append((depth, quad))
        for _, quad in sorted(sides, key=lambda s: s[0]):
            self.add(_poly(quad), *quad)
        self.add(_poly(front), *front)
        if hole:
            self.add(_poly([_p(u, v, t0) for u, v in hole], HOLE))

    def sheet(self, polyline: list[Point], length: float) -> None:
        """Тонкий лист по ломаной (профнастил): каждая полка — четырёхугольник, дальние раньше."""
        quads = []
        for (u1, v1), (u2, v2) in zip(polyline, polyline[1:], strict=False):
            quad = [_p(u1, v1), _p(u2, v2), _p(u2, v2, length), _p(u1, v1, length)]
            depth = (u1 + u2) * SHIFT[0] - (v1 + v2) * SHIFT[1]
            quads.append((depth, quad))
        for _, quad in sorted(quads, key=lambda q: q[0]):
            self.add(_poly(quad), *quad)

    def cylinder(
        self,
        r: float,
        length: float,
        t0: float = 0.0,
        cx: float = 0.0,
        cy: float = 0.0,
        hole: float = 0.0,
        ribs: int = 0,
    ) -> None:
        """Круг или труба: задний круг → полоса между касательными → торец (с отверстием у трубы)."""
        bx, by = _p(cx, cy, t0 + length)
        fx, fy = _p(cx, cy, t0)
        self.add(f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="{r:.2f}" fill="{FILL}"/>', (bx - r, by - r), (bx + r, by + r))
        # Касательные — перпендикулярно направлению сдвига
        sx, sy = SHIFT
        k = math.hypot(sx, sy)
        nx, ny = -sy / k * r, sx / k * r
        a1, a2 = (fx + nx, fy + ny), (fx - nx, fy - ny)
        b1, b2 = (bx + nx, by + ny), (bx - nx, by - ny)
        self.add(_poly([a1, b1, b2, a2], extra='stroke="none"'), a1, a2, b1, b2)
        self.add(_line(a1, b1) + _line(a2, b2))
        for i in range(1, ribs + 1):
            s = i / (ribs + 1)
            p1 = (a1[0] + (b1[0] - a1[0]) * s, a1[1] + (b1[1] - a1[1]) * s)
            s2 = min(1.0, s + 0.12)
            p2 = (a2[0] + (b2[0] - a2[0]) * s2, a2[1] + (b2[1] - a2[1]) * s2)
            self.add(_line(p1, p2))
        self.add(f'<circle cx="{fx:.2f}" cy="{fy:.2f}" r="{r:.2f}" fill="{FILL}"/>', (fx - r, fy - r), (fx + r, fy + r))
        if hole:
            self.add(f'<circle cx="{fx:.2f}" cy="{fy:.2f}" r="{hole:.2f}" fill="{HOLE}"/>')

    def svg(self, pad: float = 1.6) -> Markup:
        xs = [x for x, _ in self.points]
        ys = [y for _, y in self.points]
        x0, y0 = min(xs) - pad, min(ys) - pad
        w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
        side = max(w, h)
        x0 -= (side - w) / 2
        y0 -= (side - h) / 2
        body = "".join(self.parts)
        for tag in ("polygon", "line", "circle"):
            body = body.replace(f"<{tag} ", f'<{tag} vector-effect="non-scaling-stroke" ')
        return Markup(
            f'<svg class="icon iso" viewBox="{x0:.2f} {y0:.2f} {side:.2f} {side:.2f}" aria-hidden="true" '
            f'focusable="false" {STROKE}>{body}</svg>'
        )


def _rect(w: float, h: float, u0: float = 0.0, v0: float = 0.0) -> list[Point]:
    return [(u0, v0), (u0 + w, v0), (u0 + w, v0 + h), (u0, v0 + h)]


def _rebar() -> Icon:
    icon = Icon()
    icon.cylinder(r=6, length=30, ribs=7)
    return icon


def _round_bar() -> Icon:
    icon = Icon()
    icon.cylinder(r=6, length=30)
    return icon


def _pipe() -> Icon:
    icon = Icon()
    icon.cylinder(r=9, length=24, hole=6.5)
    return icon


def _profile_pipe() -> Icon:
    icon = Icon()
    icon.prism(_rect(18, 12), 26, hole=_rect(14, 8, 2, 2))
    return icon


def _square_bar() -> Icon:
    icon = Icon()
    icon.prism(_rect(11, 11), 30)
    return icon


def _angle() -> Icon:
    icon = Icon()
    t = 2.4
    icon.prism([(0, 0), (16, 0), (16, t), (t, t), (t, 16), (0, 16)], 26)
    return icon


def _channel() -> Icon:
    icon = Icon()
    t = 2.2
    icon.prism([(0, 0), (11, 0), (11, t), (t, t), (t, 20 - t), (11, 20 - t), (11, 20), (0, 20)], 24)
    return icon


def _beam() -> Icon:
    icon = Icon()
    t, w, h = 2.2, 16, 20
    c = w / 2
    icon.prism(
        [
            (0, 0),
            (w, 0),
            (w, t),
            (c + t / 2, t),
            (c + t / 2, h - t),
            (w, h - t),
            (w, h),
            (0, h),
            (0, h - t),
            (c - t / 2, h - t),
            (c - t / 2, t),
            (0, t),
        ],
        24,
    )
    return icon


def _strip() -> Icon:
    icon = Icon()
    icon.prism(_rect(18, 2.6), 30)
    return icon


def _sheet() -> Icon:
    icon = Icon()
    icon.prism(_rect(30, 1.8), 26)
    return icon


def _profnastil() -> Icon:
    """Лист профнастила стоит вертикально: рёбра идут сверху вниз, волна — вглубь."""
    icon = Icon()
    h = 24.0
    wave: list[tuple[float, float]] = []  # (u, t): поперёк листа и вглубь
    u = 0.0
    for _ in range(4):
        wave += [(u, 0), (u + 2.2, 0), (u + 3.4, 3), (u + 5.6, 3)]
        u += 6.8
    wave.append((u, 0))
    quads = []
    for (u1, t1), (u2, t2) in zip(wave, wave[1:], strict=False):
        quad = [_p(u1, 0, t1), _p(u2, 0, t2), _p(u2, h, t2), _p(u1, h, t1)]
        quads.append(((t1 + t2) / 2, quad))
    for _, quad in sorted(quads, key=lambda q: -q[0]):
        icon.add(_poly(quad), *quad)
    return icon


def _mesh() -> Icon:
    """Карта сетки, стоящая вертикально, ячейки на видимой грани."""
    icon = Icon()
    w, h, length = 0.9, 24, 26
    icon.prism(_rect(w, h), length)
    lines = [_line(_p(w, v, 0), _p(w, v, length)) for v in (4.8, 9.6, 14.4, 19.2)]
    lines += [_line(_p(w, 0, t), _p(w, h, t)) for t in (5.2, 10.4, 15.6, 20.8)]
    icon.add("".join(lines))
    return icon


def _pile() -> Icon:
    """Винтовая свая: ствол-труба и лопасть ближе к наконечнику."""
    icon = Icon()
    icon.cylinder(r=3.4, length=26, t0=8, hole=2.2)
    icon.cylinder(r=7.5, length=0.8, t0=6)
    icon.cylinder(r=3.4, length=6, t0=0)
    return icon


def _box() -> Icon:
    icon = Icon()
    icon.prism(_rect(18, 10), 22)
    return icon


SHAPES = {
    "rebar": _rebar,
    "round": _round_bar,
    "pipe": _pipe,
    "profile_pipe": _profile_pipe,
    "square": _square_bar,
    "angle": _angle,
    "channel": _channel,
    "beam": _beam,
    "strip": _strip,
    "sheet": _sheet,
    "profnastil": _profnastil,
    "mesh": _mesh,
    "pile": _pile,
    "box": _box,
}

# Значок раздела — по началу slug корневого раздела. Порядок важен: более точные префиксы раньше.
CATEGORY_SHAPES = (
    ("armatura", "rebar"),
    ("truba-profilnaya", "profile_pipe"),
    ("truba", "pipe"),
    ("trub", "pipe"),
    ("ugolok", "angle"),
    ("shveller", "channel"),
    ("balka", "beam"),
    ("dvutavr", "beam"),
    ("polosa", "strip"),
    ("kvadrat", "square"),
    ("krug", "round"),
    ("katanka", "round"),
    ("provoloka", "round"),
    ("list", "sheet"),
    ("profnastil", "profnastil"),
    ("krovl", "profnastil"),
    ("zabor", "profnastil"),
    ("shtaketnik", "profnastil"),
    ("setka", "mesh"),
    ("svai", "pile"),
    ("fiting", "pipe"),
)


@lru_cache(maxsize=64)
def shape_svg(shape: str) -> Markup:
    return SHAPES.get(shape, _box)().svg()


def iso_icon(slug: str) -> Markup:
    shape = next((name for prefix, name in CATEGORY_SHAPES if slug.startswith(prefix)), "box")
    return shape_svg(shape)
