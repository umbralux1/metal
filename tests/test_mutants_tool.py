"""scripts/mutants.py: какие файлы mutmut портит, а какие копирует как есть."""

from pathlib import Path

import pytest

from scripts.mutants import also_copy, part_paths


@pytest.fixture
def app(tmp_path) -> Path:
    for name in ("cart/store.py", "cart/router.py", "catalog/calculator.py", "catalog/utils.py", "main.py"):
        (tmp_path / "app" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "app" / name).write_text("")
    (tmp_path / "app" / "__pycache__").mkdir()
    return tmp_path / "app"


def test_parts_are_folders_or_files_of_app(app):
    assert part_paths(["cart", "catalog/calculator"], app) == [app / "cart", app / "catalog" / "calculator.py"]
    assert part_paths(["app/cart/", "catalog/calculator.py"], app) == [app / "cart", app / "catalog" / "calculator.py"]


def test_all_is_the_whole_app_and_nothing_inside_is_copied(app):
    assert part_paths(["all"], app) == [app]
    assert also_copy([app], app) == []


def test_without_parts_only_hints_and_runs_nothing(capsys):
    from scripts.mutants import main

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "make mutants M=cart" in out and "all" in out


def test_summary_counts_caught_and_survived(tmp_path):
    from scripts.mutants import summary

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py.meta").write_text('{"exit_code_by_key": {"m1": 1, "m2": 1, "m3": 0, "m4": 33}}')
    assert summary(tmp_path) == "Поймано 2 из 4 (50%), выжило 1, без тестов 1"
    assert summary(tmp_path / "нет") == "Результатов нет"


def test_unknown_part_names_the_known_ones(app):
    with pytest.raises(ValueError, match="Нет части сайта «склад».*cart.*catalog"):
        part_paths(["склад"], app)


def test_whole_folder_is_mutated_the_rest_is_copied(app):
    assert also_copy([app / "cart"], app) == [app / "catalog", app / "main.py"]


def test_one_file_is_mutated_its_neighbours_are_copied_one_by_one(app):
    """Папку каталога целиком не копируем: исходный calculator.py затёр бы испорченный."""
    assert also_copy([app / "catalog" / "calculator.py"], app) == [
        app / "cart",
        app / "catalog" / "utils.py",
        app / "main.py",
    ]
