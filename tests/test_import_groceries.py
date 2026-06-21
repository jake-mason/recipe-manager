"""Unit tests for import_groceries.py — no osascript or filesystem side effects."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from import_groceries import (
    _applescript_escape,
    add_to_reminders,
    parse_ingredients_json,
    resolve_ingredients_file,
)


# ---------------------------------------------------------------------------
# parse_ingredients_json
# ---------------------------------------------------------------------------

class TestParseIngredientsJson:
    def _write(self, tmp_path: Path, data: list) -> Path:
        p = tmp_path / "ingredients.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_basic_parsing(self, tmp_path):
        path = self._write(tmp_path, [
            {"name": "Chicken breast", "quantity": "1 lb", "prep_note": "", "section": "", "optional": False},
            {"name": "Garlic", "quantity": "3 cloves", "prep_note": "", "section": "", "optional": False},
        ])
        items = parse_ingredients_json(path)
        assert items == ["Chicken breast (1 lb)", "Garlic (3 cloves)"]

    def test_omits_quantity_when_empty(self, tmp_path):
        path = self._write(tmp_path, [
            {"name": "Salt", "quantity": "", "prep_note": "to taste", "section": "", "optional": False},
        ])
        items = parse_ingredients_json(path)
        assert items == ["Salt"]

    def test_skips_optional_by_default(self, tmp_path):
        path = self._write(tmp_path, [
            {"name": "Parsley", "quantity": "1 tbsp", "prep_note": "", "section": "", "optional": True},
            {"name": "Garlic", "quantity": "2 cloves", "prep_note": "", "section": "", "optional": False},
        ])
        items = parse_ingredients_json(path)
        assert items == ["Garlic (2 cloves)"]

    def test_includes_optional_when_flag_set(self, tmp_path):
        path = self._write(tmp_path, [
            {"name": "Parsley", "quantity": "1 tbsp", "prep_note": "", "section": "", "optional": True},
        ])
        items = parse_ingredients_json(path, include_optional=True)
        assert items == ["Parsley (1 tbsp)"]

    def test_skips_empty_name(self, tmp_path):
        path = self._write(tmp_path, [
            {"name": "", "quantity": "1 cup", "prep_note": "", "section": "", "optional": False},
            {"name": "Flour", "quantity": "2 cups", "prep_note": "", "section": "", "optional": False},
        ])
        items = parse_ingredients_json(path)
        assert items == ["Flour (2 cups)"]

    def test_empty_list(self, tmp_path):
        path = self._write(tmp_path, [])
        assert parse_ingredients_json(path) == []

    def test_fixture(self, ingredients_json_path):
        items = parse_ingredients_json(ingredients_json_path)
        assert "Chicken breast (1 lb)" in items
        assert "Garlic (3 cloves)" in items
        assert "Heavy cream (1 cup)" in items
        assert "Sun-dried tomatoes (1/2 cup)" in items


# ---------------------------------------------------------------------------
# _applescript_escape
# ---------------------------------------------------------------------------

class TestApplescriptEscape:
    def test_clean_string(self):
        assert _applescript_escape("Chicken breast") == "Chicken breast"

    def test_double_quote_escaped(self):
        assert _applescript_escape('Say "hello"') == 'Say \\"hello\\"'

    def test_backslash_escaped(self):
        assert _applescript_escape("back\\slash") == "back\\\\slash"

    def test_both_escaped(self):
        result = _applescript_escape('path\\to\\"file"')
        assert "\\\\" in result
        assert '\\"' in result


# ---------------------------------------------------------------------------
# resolve_ingredients_file
# ---------------------------------------------------------------------------

class TestResolveIngredientsFile:
    def test_slug_resolves_via_recipes_formatted(self, recipe_data_dir):
        path = resolve_ingredients_file("tuscan-chicken", None, recipe_data_dir)
        assert path.name == "ingredients.json"
        assert path.exists()

    def test_explicit_file_path(self, ingredients_json_path):
        path = resolve_ingredients_file(None, ingredients_json_path, Path("/unused"))
        assert path == ingredients_json_path.resolve()

    def test_explicit_dir_path_appends_filename(self, ingredients_json_path):
        dir_path = ingredients_json_path.parent
        path = resolve_ingredients_file(None, dir_path, Path("/unused"))
        assert path.name == "ingredients.json"

    def test_missing_slug_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_ingredients_file("nonexistent-recipe", None, tmp_path)

    def test_missing_both_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            resolve_ingredients_file(None, None, tmp_path)

    def test_missing_file_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_ingredients_file(None, tmp_path / "does_not_exist.json", tmp_path)


# ---------------------------------------------------------------------------
# add_to_reminders — dry-run (no osascript)
# ---------------------------------------------------------------------------

class TestAddToRemindersDryRun:
    def test_dry_run_returns_zero(self, capsys):
        count = add_to_reminders(["Egg (2)", "Butter (1 tbsp)"], dry_run=True)
        assert count == 0

    def test_dry_run_prints_items(self, capsys):
        add_to_reminders(["Egg (2)", "Milk (1 cup)"], dry_run=True)
        captured = capsys.readouterr()
        assert "Egg (2)" in captured.out
        assert "Milk (1 cup)" in captured.out

    def test_empty_items_returns_zero(self):
        count = add_to_reminders([], dry_run=True)
        assert count == 0

    def test_dry_run_never_calls_osascript(self):
        with patch("import_groceries._run_osascript") as mock_osa:
            add_to_reminders(["Egg (2)"], dry_run=True)
            mock_osa.assert_not_called()
