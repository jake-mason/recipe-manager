"""Unit tests for parse_recipe.py — pure logic, no network or LLM calls."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parse_recipe import (
    Ingredient,
    _instruction_lines,
    _recipe_objects_from_json_ld,
    extract_json_ld_recipe,
    get_images_from_bytes,
    is_url,
    recipe_from_json_ld,
    slugify,
    write_recipe_output,
)
from tests.conftest import SAMPLE_JSON_LD_HTML


# ---------------------------------------------------------------------------
# is_url
# ---------------------------------------------------------------------------

class TestIsUrl:
    def test_http(self):
        assert is_url("http://example.com/recipe") is True

    def test_https(self):
        assert is_url("https://www.food.com/recipe/123") is True

    def test_file_path(self):
        assert is_url("/path/to/recipe.pdf") is False

    def test_relative_path(self):
        assert is_url("recipe.pdf") is False

    def test_ftp(self):
        assert is_url("ftp://example.com/file") is False

    def test_empty(self):
        assert is_url("") is False

    def test_no_netloc(self):
        assert is_url("http://") is False


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert slugify("Tuscan Chicken") == "tuscan-chicken"

    def test_special_chars(self):
        assert slugify("Pasta & Meatballs!") == "pasta-meatballs"

    def test_truncates_to_4_words(self):
        assert slugify("one two three four five six") == "one-two-three-four"

    def test_multiple_spaces(self):
        assert slugify("  spaced   out  ") == "spaced-out"

    def test_already_slug(self):
        assert slugify("tuscan-chicken") == "tuscan-chicken"

    def test_empty(self):
        assert slugify("") == "unknown-recipe"

    def test_only_special_chars(self):
        assert slugify("!!!") == "unknown-recipe"

    def test_numbers_preserved(self):
        assert slugify("3 cheese pizza") == "3-cheese-pizza"


# ---------------------------------------------------------------------------
# _instruction_lines
# ---------------------------------------------------------------------------

class TestInstructionLines:
    def test_plain_string(self):
        assert _instruction_lines("Boil water.") == ["Boil water."]

    def test_empty_string(self):
        assert _instruction_lines("") == []

    def test_whitespace_string(self):
        assert _instruction_lines("   ") == []

    def test_list_of_strings(self):
        assert _instruction_lines(["Step one.", "Step two."]) == ["Step one.", "Step two."]

    def test_list_of_dicts_text_key(self):
        instructions = [{"@type": "HowToStep", "text": "Mix ingredients."}]
        assert _instruction_lines(instructions) == ["Mix ingredients."]

    def test_list_of_dicts_name_key(self):
        instructions = [{"name": "Preheat oven."}]
        assert _instruction_lines(instructions) == ["Preheat oven."]

    def test_mixed_list(self):
        instructions = ["First step.", {"text": "Second step."}, ""]
        assert _instruction_lines(instructions) == ["First step.", "Second step."]

    def test_empty_list(self):
        assert _instruction_lines([]) == []

    def test_dict_empty_text(self):
        assert _instruction_lines([{"text": "  "}]) == []


# ---------------------------------------------------------------------------
# _recipe_objects_from_json_ld
# ---------------------------------------------------------------------------

class TestRecipeObjectsFromJsonLd:
    def test_flat_recipe_dict(self):
        data = {"@type": "Recipe", "name": "Soup"}
        result = _recipe_objects_from_json_ld(data)
        assert len(result) == 1
        assert result[0]["name"] == "Soup"

    def test_type_list(self):
        data = {"@type": ["Recipe", "Thing"], "name": "Cake"}
        result = _recipe_objects_from_json_ld(data)
        assert len(result) == 1

    def test_no_match(self):
        data = {"@type": "WebPage", "name": "Blog"}
        assert _recipe_objects_from_json_ld(data) == []

    def test_graph_nested(self):
        data = {
            "@graph": [
                {"@type": "WebPage"},
                {"@type": "Recipe", "name": "Stew"},
            ]
        }
        result = _recipe_objects_from_json_ld(data)
        assert len(result) == 1
        assert result[0]["name"] == "Stew"

    def test_main_entity(self):
        data = {"mainEntity": {"@type": "Recipe", "name": "Pie"}}
        result = _recipe_objects_from_json_ld(data)
        assert len(result) == 1

    def test_list_input(self):
        data = [{"@type": "Recipe", "name": "Tacos"}, {"@type": "Thing"}]
        result = _recipe_objects_from_json_ld(data)
        assert len(result) == 1
        assert result[0]["name"] == "Tacos"

    def test_empty_dict(self):
        assert _recipe_objects_from_json_ld({}) == []


# ---------------------------------------------------------------------------
# extract_json_ld_recipe
# ---------------------------------------------------------------------------

class TestExtractJsonLdRecipe:
    def test_finds_recipe(self):
        result = extract_json_ld_recipe(SAMPLE_JSON_LD_HTML)
        assert result is not None
        assert result["name"] == "Classic Lasagna"

    def test_returns_none_when_absent(self):
        html = "<html><body><p>No JSON-LD here.</p></body></html>"
        assert extract_json_ld_recipe(html) is None

    def test_skips_malformed_json(self):
        html = '<script type="application/ld+json">{ not json }</script>'
        assert extract_json_ld_recipe(html) is None

    def test_multiple_scripts_returns_first_recipe(self):
        html = """
        <script type="application/ld+json">{"@type": "WebPage"}</script>
        <script type="application/ld+json">{"@type": "Recipe", "name": "First"}</script>
        <script type="application/ld+json">{"@type": "Recipe", "name": "Second"}</script>
        """
        result = extract_json_ld_recipe(html)
        assert result is not None
        assert result["name"] == "First"

    def test_empty_script_skipped(self):
        html = '<script type="application/ld+json">   </script>'
        assert extract_json_ld_recipe(html) is None


# ---------------------------------------------------------------------------
# recipe_from_json_ld
# ---------------------------------------------------------------------------

class TestRecipeFromJsonLd:
    def _base_recipe(self):
        return {
            "name": "Classic Lasagna",
            "recipeIngredient": ["Lasagna noodles (12)", "Ricotta cheese (2 cups)"],
            "recipeInstructions": [
                {"text": "Boil noodles."},
                {"text": "Layer with cheese."},
            ],
        }

    def test_slug(self):
        slug, _, _ = recipe_from_json_ld(self._base_recipe())
        assert slug == "classic-lasagna"

    def test_ingredients_structured(self):
        _, ingredients, _ = recipe_from_json_ld(self._base_recipe())
        names = [i.name for i in ingredients]
        assert "Lasagna noodles (12)" in names
        assert "Ricotta cheese (2 cups)" in names

    def test_steps_markdown(self):
        _, _, steps = recipe_from_json_ld(self._base_recipe())
        assert "1. Boil noodles." in steps
        assert "2. Layer with cheese." in steps

    def test_missing_instructions(self):
        recipe = self._base_recipe()
        del recipe["recipeInstructions"]
        _, _, steps = recipe_from_json_ld(recipe)
        assert steps == ""

    def test_ingredients_as_string(self):
        recipe = self._base_recipe()
        recipe["recipeIngredient"] = "Egg (1)\nButter (2 tbsp)"
        _, ingredients, _ = recipe_from_json_ld(recipe)
        names = [i.name for i in ingredients]
        assert "Egg (1)" in names
        assert "Butter (2 tbsp)" in names

    def test_missing_name_falls_back(self):
        recipe = {"recipeIngredient": [], "recipeInstructions": []}
        slug, _, _ = recipe_from_json_ld(recipe)
        assert slug == "unknown-recipe"

    def test_headline_used_when_no_name(self):
        recipe = {
            "headline": "Banana Bread",
            "recipeIngredient": [],
            "recipeInstructions": [],
        }
        slug, _, _ = recipe_from_json_ld(recipe)
        assert slug == "banana-bread"


# ---------------------------------------------------------------------------
# get_images_from_bytes
# ---------------------------------------------------------------------------

class TestGetImagesFromBytes:
    def test_raw_png_passthrough(self):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = get_images_from_bytes(png_bytes, mime_hint="image/png")
        assert result == [png_bytes]

    def test_pdf_magic_bytes_triggers_pdf_path(self):
        fake_page = MagicMock()
        fake_page.get_pixmap.return_value.tobytes.return_value = b"page_png_data"
        fake_doc = MagicMock()
        fake_doc.__iter__ = MagicMock(return_value=iter([fake_page]))

        with patch("parse_recipe.fitz.open", return_value=fake_doc):
            result = get_images_from_bytes(b"%PDF-1.4 fake content")

        assert result == [b"page_png_data"]

    def test_pdf_mime_hint_triggers_pdf_path(self):
        fake_page = MagicMock()
        fake_page.get_pixmap.return_value.tobytes.return_value = b"page_png_data"
        fake_doc = MagicMock()
        fake_doc.__iter__ = MagicMock(return_value=iter([fake_page]))

        with patch("parse_recipe.fitz.open", return_value=fake_doc):
            result = get_images_from_bytes(b"not really pdf", mime_hint="application/pdf")

        assert result == [b"page_png_data"]

    def test_pdf_name_hint_triggers_pdf_path(self):
        fake_doc = MagicMock()
        fake_doc.__iter__ = MagicMock(return_value=iter([]))

        with patch("parse_recipe.fitz.open", return_value=fake_doc):
            result = get_images_from_bytes(b"data", name_hint="recipe.pdf")

        assert result == []

    def test_fitz_error_returns_empty(self):
        with patch("parse_recipe.fitz.open", side_effect=Exception("corrupt")):
            result = get_images_from_bytes(b"%PDF-bad")
        assert result == []


# ---------------------------------------------------------------------------
# write_recipe_output
# ---------------------------------------------------------------------------

def _ing(name: str, quantity: str = "") -> Ingredient:
    return Ingredient(name=name, quantity=quantity, prep_note="", section="", optional=False)


class TestWriteRecipeOutput:
    def test_creates_files(self, tmp_path):
        ingredients_file, steps_file = write_recipe_output(
            str(tmp_path), "test-recipe", [_ing("Egg", "2")], "1. Boil water."
        )
        assert ingredients_file.exists()
        assert steps_file.exists()

    def test_ingredients_content(self, tmp_path):
        ingredients_file, _ = write_recipe_output(
            str(tmp_path), "test-recipe", [_ing("Egg", "2")], "1. Boil."
        )
        data = json.loads(ingredients_file.read_text())
        assert any(i["name"] == "Egg" and i["quantity"] == "2" for i in data)

    def test_steps_content(self, tmp_path):
        _, steps_file = write_recipe_output(
            str(tmp_path), "test-recipe", [_ing("Egg", "2")], "1. Boil."
        )
        content = steps_file.read_text()
        assert content.startswith("# Steps\n")
        assert "1. Boil." in content

    def test_empty_ingredients_writes_empty_array(self, tmp_path):
        ingredients_file, _ = write_recipe_output(str(tmp_path), "test-recipe", [], "")
        assert json.loads(ingredients_file.read_text()) == []

    def test_empty_steps_writes_fallback(self, tmp_path):
        _, steps_file = write_recipe_output(str(tmp_path), "test-recipe", [], "")
        assert "No steps/instructions found." in steps_file.read_text()

    def test_creates_nested_directory(self, tmp_path):
        write_recipe_output(str(tmp_path / "output"), "new-recipe", [_ing("Flour", "1 cup")], "1. Mix.")
        assert (tmp_path / "output" / "new-recipe" / "ingredients.json").exists()
