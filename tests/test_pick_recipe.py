"""Unit tests for pick_recipe.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from groceries.pick_recipe import find_recipes, pick_with_fzf


# ---------------------------------------------------------------------------
# find_recipes
# ---------------------------------------------------------------------------

class TestFindRecipes:
    def test_returns_sorted_slugs(self, tmp_path):
        for slug in ("zucchini-bread", "apple-pie", "beef-stew"):
            d = tmp_path / "recipes-formatted" / slug
            d.mkdir(parents=True)
            (d / "ingredients.json").write_text('[{"name": "Ingredient", "quantity": "", "prep_note": "", "section": "", "optional": false}]')

        recipes = find_recipes(tmp_path)
        assert recipes == ["apple-pie", "beef-stew", "zucchini-bread"]

    def test_skips_dirs_without_ingredients(self, tmp_path):
        good = tmp_path / "recipes-formatted" / "good-recipe"
        good.mkdir(parents=True)
        (good / "ingredients.json").write_text('[{"name": "Egg", "quantity": "", "prep_note": "", "section": "", "optional": false}]')

        bad = tmp_path / "recipes-formatted" / "bad-recipe"
        bad.mkdir(parents=True)
        # No ingredients.json

        recipes = find_recipes(tmp_path)
        assert recipes == ["good-recipe"]

    def test_returns_empty_when_no_formatted_dir(self, tmp_path):
        assert find_recipes(tmp_path) == []

    def test_returns_empty_when_formatted_dir_empty(self, tmp_path):
        (tmp_path / "recipes-formatted").mkdir()
        assert find_recipes(tmp_path) == []

    def test_uses_fixture_data_dir(self, recipe_data_dir):
        recipes = find_recipes(recipe_data_dir)
        assert recipes == ["tuscan-chicken"]


# ---------------------------------------------------------------------------
# pick_with_fzf
# ---------------------------------------------------------------------------

class TestPickWithFzf:
    def _mock_run(self, returncode, stdout=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        return result

    def test_returns_selection_on_success(self):
        with patch("groceries.pick_recipe.subprocess.run", return_value=self._mock_run(0, "tuscan-chicken\n")):
            assert pick_with_fzf(["tuscan-chicken", "apple-pie"]) == "tuscan-chicken"

    def test_returns_none_on_cancel(self):
        with patch("groceries.pick_recipe.subprocess.run", return_value=self._mock_run(1, "")):
            assert pick_with_fzf(["tuscan-chicken"]) is None

    def test_returns_none_on_empty_stdout(self):
        with patch("groceries.pick_recipe.subprocess.run", return_value=self._mock_run(0, "  ")):
            assert pick_with_fzf(["tuscan-chicken"]) is None

    def test_returns_sentinel_when_fzf_missing(self):
        with patch("groceries.pick_recipe.subprocess.run", side_effect=FileNotFoundError):
            assert pick_with_fzf(["any-recipe"]) == "FZF_NOT_FOUND"
