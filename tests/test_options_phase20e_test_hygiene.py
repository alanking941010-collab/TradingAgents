"""Phase 20E tests for options test-fixture hygiene and lint gate scope."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = PROJECT_ROOT / "tests"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _options_test_files() -> list[Path]:
    return sorted(TESTS_ROOT.glob("test_options*.py"))


def _fixture_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                func = decorator.func
            else:
                func = decorator
            if isinstance(func, ast.Attribute) and func.attr == "fixture":
                names.add(node.name)
            elif isinstance(func, ast.Name) and func.id == "fixture":
                names.add(node.name)
    return names


def test_shfe_options_db_fixture_is_centralized_in_conftest():
    fixture_definers = {
        path.name: _fixture_function_names(path)
        for path in _options_test_files()
        if "shfe_options_db" in _fixture_function_names(path)
    }

    assert fixture_definers == {}
    assert "def shfe_options_db" in (TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")


def test_options_tests_do_not_import_pytest_fixtures_from_other_test_modules():
    offenders: dict[str, list[str]] = {}
    for path in _options_test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not (node.module or "").startswith("tests.test_options_"):
                continue
            imported = {alias.name for alias in node.names}
            if "shfe_options_db" in imported:
                offenders.setdefault(path.name, []).append(node.module or "")

    assert offenders == {}


def test_pyproject_defines_options_only_ruff_gate():
    pyproject = PYPROJECT.read_text(encoding="utf-8")

    assert "[tool.ruff]" in pyproject
    assert "target-version" in pyproject
    assert "[tool.ruff.lint]" in pyproject
    assert '"F"' in pyproject and '"E"' in pyproject
