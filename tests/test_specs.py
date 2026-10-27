"""Спецификации и тесты связаны (конституция, принцип III): у каждого требования — тест, у каждой ссылки — требование.

Требование — строка `**FR-###**` в `specs/NNN-имя/spec.md`. Тест ссылается на него в описании: `NNN:FR-###`
(номер спецификации и требования, например `004:FR-002`). Проверяется:
- у реализованной спецификации (статус «Реализовано») на каждое действующее требование есть хотя бы один тест;
  отменённое требование помечается «(отменено)» и тест не требует;
- каждая ссылка `NNN:FR-###` в тестах ведёт на существующее требование — опечатка или удалённое требование видны сразу.
Пока спецификация в черновике или согласована, тестов на неё может ещё не быть.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENT = re.compile(r"\*\*FR-(\d{3})\*\*(.*)")
REFERENCE = re.compile(r"\b(\d{3}):FR-(\d{3})\b")
STATUS = re.compile(r"\*\*Статус[^*]*\*\*:\s*(\S+)")


def spec_requirements(specs_dir: Path) -> dict[str, tuple[str, set[str]]]:
    """Номер спецификации → (статус, действующие требования «NNN:FR-###»)."""
    found: dict[str, tuple[str, set[str]]] = {}
    for spec in sorted(specs_dir.glob("[0-9][0-9][0-9]-*/spec.md")):
        number = spec.parent.name[:3]
        text = spec.read_text(encoding="utf-8")
        status = STATUS.search(text)
        active = {f"{number}:FR-{fr}" for fr, rest in REQUIREMENT.findall(text) if "(отменено)" not in rest.lower()}
        found[number] = (status.group(1) if status else "", active)
    return found


def all_requirements(specs_dir: Path) -> set[str]:
    """Все требования, включая отменённые, — на них ещё могут ссылаться старые тесты."""
    return {
        f"{spec.parent.name[:3]}:FR-{fr}"
        for spec in specs_dir.glob("[0-9][0-9][0-9]-*/spec.md")
        for fr, _ in REQUIREMENT.findall(spec.read_text(encoding="utf-8"))
    }


def references_in_tests(tests_dir: Path) -> dict[str, list[str]]:
    """Ссылка «NNN:FR-###» → файлы тестов, где она встречается."""
    refs: dict[str, list[str]] = {}
    for path in sorted(tests_dir.rglob("test_*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue  # в этом файле ссылки — примеры
        for number, fr in REFERENCE.findall(path.read_text(encoding="utf-8")):
            refs.setdefault(f"{number}:FR-{fr}", []).append(path.name)
    return refs


def untested(specs_dir: Path, tests_dir: Path) -> list[str]:
    refs = references_in_tests(tests_dir)
    return sorted(
        req
        for status, active in spec_requirements(specs_dir).values()
        if status.lower().startswith("реализован")
        for req in active
        if req not in refs
    )


def dangling(specs_dir: Path, tests_dir: Path) -> list[str]:
    known = all_requirements(specs_dir)
    return sorted(
        f"{ref} ({', '.join(files)})" for ref, files in references_in_tests(tests_dir).items() if ref not in known
    )


def test_every_requirement_of_implemented_spec_has_a_test():
    missing = untested(ROOT / "specs", ROOT / "tests")
    assert missing == [], "нет тестов на требования (в описании теста — «NNN:FR-###»):\n" + "\n".join(missing)


def test_every_reference_points_to_a_requirement():
    wrong = dangling(ROOT / "specs", ROOT / "tests")
    assert wrong == [], "ссылки на несуществующие требования:\n" + "\n".join(wrong)


# Сама проверка — на маленьком примере: спецификация 007 реализована, 008 — черновик


def _example(tmp_path: Path) -> tuple[Path, Path]:
    specs, tests = tmp_path / "specs", tmp_path / "tests"
    (specs / "007-limit").mkdir(parents=True)
    (specs / "007-limit" / "spec.md").write_text(
        "**Статус (Status)**: Реализовано\n"
        "- **FR-001**: Сайт ДОЛЖЕН …\n- **FR-002**: Сайт ДОЛЖЕН …\n- **FR-003** (отменено): …\n",
        encoding="utf-8",
    )
    (specs / "008-draft").mkdir()
    (specs / "008-draft" / "spec.md").write_text(
        "**Статус (Status)**: Черновик (Draft)\n- **FR-001**: …\n", encoding="utf-8"
    )
    tests.mkdir()
    (tests / "test_limit.py").write_text('def test_a():\n    """007:FR-001: …"""\n    """007:FR-009"""\n')
    return specs, tests


def test_checker_finds_untested_requirements_only_in_implemented_specs(tmp_path):
    specs, tests = _example(tmp_path)
    assert untested(specs, tests) == ["007:FR-002"]  # отменённое FR-003 и черновик 008 тестов не требуют


def test_checker_finds_references_to_missing_requirements(tmp_path):
    specs, tests = _example(tmp_path)
    assert dangling(specs, tests) == ["007:FR-009 (test_limit.py)"]
