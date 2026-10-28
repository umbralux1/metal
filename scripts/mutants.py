"""Мутационное тестирование частей сайта: mutmut портит код и смотрит, замечают ли это тесты.

    make mutants                         — подсказка: какие части сайта есть (сам прогон не запускается)
    make mutants M="delivery"            — доставка
    make mutants M="catalog/calculator"  — один файл каталога: калькулятор
    make mutants M="cart leads delivery" — несколько частей сразу
    make mutants M=all                   — весь сайт (несколько часов)
    python -m scripts.mutants cart --show app.cart.store.x_add__mutmut_7   — что именно испортили

Часть сайта — папка или файл в app/: cart, leads, delivery, seo, admin, catalog, catalog/calculator…
В конце — список выживших: порча, которую тесты не заметили. Браузерные тесты под mutmut пропускаются
(tests/conftest.py). Прогон долгий: корзина и заявки ~40 минут, калькулятор и доставка ~30.

Настройки mutmut собираются здесь, а не в pyproject.toml: какие файлы портить — из аргументов, остальной сайт
копируется как есть (`also_copy`). Поэтому `mutmut results` и `mutmut show` напрямую запускать не нужно —
только через этот скрипт: он передаёт mutmut те же части сайта.
"""

import argparse
import shutil
import sys
from pathlib import Path

APP = Path("app")
ALL = "all"
DO_NOT_MUTATE = ["app/catalog/demo_catalog.py"]  # данные демо-каталога, а не логика
ALSO_COPY_OUTSIDE_APP = ["migrations/", "alembic.ini", "main.py", "scripts/", "deploy/", "specs/"]


def part_paths(parts: list[str], app: Path = APP) -> list[Path]:
    """«cart» → app/cart, «catalog/calculator» → app/catalog/calculator.py, «all» → весь app. Нет такой части — ValueError."""
    if ALL in parts:
        return [app]
    paths = []
    for part in parts:
        name = part.strip("/").removeprefix("app/").removesuffix(".py")
        for candidate in (app / name, app / f"{name}.py"):
            if candidate.exists():
                paths.append(candidate)
                break
        else:
            raise ValueError(f"Нет части сайта «{part}». {known_parts(app)}")
    return paths


def known_parts(app: Path = APP) -> str:
    names = sorted(p.stem for p in app.iterdir() if not p.name.startswith("_") and p.name != "__pycache__")
    return f"Есть: {', '.join(names)}, или файл (например catalog/calculator), или {ALL} — весь сайт"


def also_copy(mutate: list[Path], app: Path = APP) -> list[Path]:
    """Всё в app/, кроме того, что портим: mutmut копирует это без изменений, чтобы сайт запускался.

    Папку, внутри которой портим один файл, не копируем целиком — иначе исходный файл затрёт испорченный.
    """
    if app in mutate:
        return []  # портим весь app — копировать из него нечего
    keep: list[Path] = []

    def walk(folder: Path) -> None:
        for entry in sorted(folder.iterdir()):
            if entry.name == "__pycache__" or entry in mutate:
                continue
            if any(entry in target.parents for target in mutate):
                walk(entry)  # внутри портим что-то одно — копируем остальное по отдельности
            else:
                keep.append(entry)

    walk(app)
    return keep


def configure(parts: list[str]) -> None:
    """Подменяет настройки mutmut: что портить и что копировать как есть."""
    import mutmut.__main__ as mm  # именно так: при `python -m mutmut` модуль грузится дважды и mutmut падает

    mutate = part_paths(parts)
    ours = {
        "paths_to_mutate": [str(p) for p in mutate],
        "do_not_mutate": DO_NOT_MUTATE,
        "also_copy": [*(str(p) for p in also_copy(mutate)), *ALSO_COPY_OUTSIDE_APP],
    }
    original = mm.config_reader

    def config_reader():
        theirs = original()
        return lambda key, default: ours[key] if key in ours else theirs(key, default)

    mm.config_reader = config_reader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Мутационное тестирование частей сайта (mutmut)")
    parser.add_argument("parts", nargs="*", help="части сайта: cart leads delivery … или all")
    parser.add_argument("--show", metavar="MUTANT", help="показать, что испорчено в выжившем (имя из списка)")
    args = parser.parse_args(argv)
    if not args.parts:  # долгий прогон только по явной просьбе
        print('Укажите часть сайта: make mutants M=cart (несколько — M="cart leads", весь сайт — M=all).')
        print(known_parts())
        return 0
    try:
        configure(args.parts)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    import mutmut.__main__ as mm

    if args.show:
        mm.cli(["show", args.show], standalone_mode=False)
        return 0
    shutil.rmtree("mutants", ignore_errors=True)  # старые результаты другой части сайта только путают
    print(f"Портим: {', '.join(str(p) for p in part_paths(args.parts))}")
    try:
        mm.cli(["run", "--max-children", "1"], standalone_mode=False)  # база одна — тесты по одному
    except SystemExit as exc:
        if exc.code:
            return int(exc.code)
    mm.cli(["results"], standalone_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
