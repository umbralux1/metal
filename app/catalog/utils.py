import re

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

# «40х20х2», «40×20×2», «40*20*2» → «40x20x2»
_SIZE_SEP = re.compile(r"(?<=\d)\s*[xх×*]\s*(?=\d)", re.IGNORECASE)


def normalize_search(text: str) -> str:
    """Текст для поиска: нижний регистр, ё→е, единый разделитель размеров, без лишних пробелов."""
    text = text.lower().replace("ё", "е")
    text = _SIZE_SEP.sub("x", text)
    text = re.sub(r"[^\w.,x]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    """ЧПУ на латинице: «Труба 40×20×2» → «truba-40x20x2»."""
    text = _SIZE_SEP.sub("x", text.lower())
    out = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    out = re.sub(r"[^a-z0-9]+", "-", out)
    return out.strip("-")
