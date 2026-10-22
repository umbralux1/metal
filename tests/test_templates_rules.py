"""Правила шаблонов из CLAUDE.md, которые можно проверить по тексту."""

import re
from pathlib import Path

TEMPLATES = Path("app/templates")

# Где разрешён |safe: файл → сколько раз и почему. Новое место — только своим HTML, с причиной.
SAFE_ALLOWED = {
    "base.html": 1,  # JSON-LD: app/seo/jsonld.to_script экранирует «</»
    "catalog/listing.html": 1,  # SEO-текст из админки — долг: docs/tech-debt.md, «SEO-текст без очистки»
    "catalog/product.html": 1,  # то же
}


def templates() -> dict[str, str]:
    return {str(p.relative_to(TEMPLATES)): p.read_text(encoding="utf-8") for p in TEMPLATES.rglob("*.html")}


def test_safe_filter_only_in_allowed_places():
    found = {name: len(re.findall(r"\|\s*safe\b", text)) for name, text in templates().items()}
    found = {name: n for name, n in found.items() if n}
    assert found == SAFE_ALLOWED, "|safe отключает экранирование — см. «Безопасность» в CLAUDE.md"


def test_autoescape_is_not_disabled():
    for name, text in templates().items():
        assert "autoescape false" not in text, name


def test_images_have_size():
    """width и height у картинок: без них страница прыгает при загрузке (CLS)."""
    for name, text in templates().items():
        for tag in re.findall(r"<img\b[^>]*>", text):
            assert "width=" in tag and "height=" in tag, f"{name}: {tag}"
