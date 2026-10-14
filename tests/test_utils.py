import pytest

from app.catalog.utils import normalize_search, slugify
from app.core.templating import format_rub
from app.seo.middleware import canonical_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Труба 40х20х2", "труба 40x20x2"),
        ("ТРУБА 40×20×2", "труба 40x20x2"),
        ("труба 40 * 20 * 2", "труба 40x20x2"),
        ("Арматура   Ёлочка", "арматура елочка"),
    ],
)
def test_normalize_search(raw, expected):
    assert normalize_search(raw) == expected


def test_slugify():
    assert slugify("Труба профильная 40×20×2") == "truba-profilnaya-40x20x2"
    assert slugify("Швеллер 14П") == "shveller-14p"


@pytest.mark.parametrize(("kop", "text"), [(4325, "43,25 ₽"), (4870000, "48 700 ₽"), (None, "")])
def test_format_rub(kop, text):
    assert format_rub(kop) == text


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/catalog/armatura/", None),
        ("/catalog/armatura", "/catalog/armatura/"),
        ("/robots.txt", None),
        ("/static/css/main.css", None),
        ("/health", None),
    ],
)
def test_canonical_path(path, expected):
    assert canonical_path(path) == expected
