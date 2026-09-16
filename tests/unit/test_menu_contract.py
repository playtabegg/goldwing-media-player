"""The factory calls our menu renderer; this checks the call, not a copy of it.

``rialto2/rialto_core/film_menu_author.py`` imports names from
``rialto_core.film_menus``, which re-exports ``wti_player.menu``, and then
calls ``render_menu`` with keyword arguments and reads fields off what comes
back. Both sides have their own tests; this one reads the factory's source
with ``ast`` and holds the Player to exactly what it uses, so a rename here
fails here rather than on the factory PC. Skips when rialto2 is not beside
this checkout.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from wti_player import menu

FACTORY = Path(__file__).resolve().parents[2].parent / "rialto2"
CALLER = FACTORY / "rialto_core" / "film_menu_author.py"
SHIM = FACTORY / "rialto_core" / "film_menus.py"


@pytest.fixture(scope="module")
def caller() -> ast.Module:
    if not CALLER.is_file():
        pytest.skip(f"the factory is not at {FACTORY}")
    return ast.parse(CALLER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def shim_names() -> set[str]:
    if not SHIM.is_file():
        pytest.skip(f"the factory is not at {FACTORY}")
    tree = ast.parse(SHIM.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                value = node.value
                if isinstance(target, ast.Name) and isinstance(value, ast.Attribute):
                    if isinstance(value.value, ast.Name) and value.value.id == "menu":
                        names.add(value.attr)
    return names


def imported_from_film_menus(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "rialto_core.film_menus":
            names.update(alias.name for alias in node.names)
    return names


def keyword_args_to(tree: ast.Module, function: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function:
            found.update(kw.arg for kw in node.keywords if kw.arg)
    return found


def attributes_read_from(tree: ast.Module, variable: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == variable:
            found.add(node.attr)
    return found


class TestTheNamesTheFactoryImports:
    def test_every_name_the_shim_re_exports_exists_on_wti_player_menu(self, shim_names: set[str]) -> None:
        missing = sorted(name for name in shim_names if not hasattr(menu, name))
        assert missing == []

    def test_every_name_the_author_imports_is_re_exported(self, caller: ast.Module, shim_names: set[str]) -> None:
        wanted = imported_from_film_menus(caller) - {"FilmMenusUnavailable", "wti_player_root"}
        assert wanted, "the factory imports nothing from the shim?"
        assert sorted(wanted - shim_names) == []


class TestTheCall:
    def test_render_menu_accepts_every_keyword_the_factory_passes(self, caller: ast.Module) -> None:
        passed = keyword_args_to(caller, "render_menu")
        params = inspect.signature(menu.render_menu).parameters
        assert passed, "the factory does not call render_menu by keyword?"
        assert sorted(passed - set(params)) == []

    def test_button_is_built_the_way_the_factory_builds_it(self, caller: ast.Module) -> None:
        passed = keyword_args_to(caller, "Button")
        fields = set(inspect.signature(menu.Button).parameters)
        assert passed, "the factory does not build a Button by keyword?"
        assert sorted(passed - fields) == []

    def test_the_menu_is_drawn_at_the_size_the_factory_encodes(self, caller: ast.Module) -> None:
        names = imported_from_film_menus(caller)
        assert {"MENU_WIDTH", "MENU_HEIGHT"} <= names
        assert (menu.MENU_WIDTH, menu.MENU_HEIGHT) == (1920, 1080)


class TestWhatComesBack:
    def test_rendered_menu_carries_every_field_the_factory_reads(self, caller: ast.Module) -> None:
        read = attributes_read_from(caller, "rendered")
        fields = set(inspect.signature(menu.RenderedMenu).parameters)
        assert read, "the factory reads nothing off the rendered menu?"
        assert sorted(read - fields) == []

    def test_rendered_button_carries_every_field_the_factory_reads(self, caller: ast.Module) -> None:
        read = attributes_read_from(caller, "button") - {"key"}  # `button.key` is also the hdmv.Button local
        fields = set(inspect.signature(menu.RenderedButton).parameters) | {"key"}
        assert read, "the factory reads nothing off a rendered button?"
        assert sorted(read - fields) == []

    def test_the_three_button_states_the_factory_expects_are_the_ones_we_render(self, caller: ast.Module) -> None:
        source = CALLER.read_text(encoding="utf-8")
        for state in ("normal", "selected", "activated"):
            assert f'"{state}"' in source
        assert tuple(menu.BUTTON_STATES) == ("normal", "selected", "activated")
