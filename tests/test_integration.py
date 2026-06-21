"""Integration tests — mock at the network/subprocess/LLM boundary."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parse_recipe import load_recipe_source, write_recipe_output
from tests.conftest import SAMPLE_JSON_LD_HTML, SAMPLE_PLAIN_HTML


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetch_response(body: bytes, content_type: str):
    """Return a (body, content_type) tuple as fetch_url would."""
    return body, content_type


# ---------------------------------------------------------------------------
# load_recipe_source — URL branch
# ---------------------------------------------------------------------------

class TestLoadRecipeSourceUrl:
    def test_url_with_json_ld_returns_preparsed(self):
        html_bytes = SAMPLE_JSON_LD_HTML.encode()
        with patch("parse_recipe.fetch_url", return_value=(html_bytes, "text/html")):
            result = load_recipe_source("https://example.com/recipe")

        assert "preparsed" in result
        slug, ingredients, steps = result["preparsed"]
        assert slug == "classic-lasagna"
        assert any(i.name == "Lasagna noodles (12)" for i in ingredients)
        assert "Boil noodles" in steps

    def test_url_with_plain_html_returns_text(self):
        html_bytes = SAMPLE_PLAIN_HTML.encode()
        with patch("parse_recipe.fetch_url", return_value=(html_bytes, "text/html")):
            result = load_recipe_source("https://example.com/recipe")

        assert "text" in result
        assert result["text"]  # non-empty
        assert result.get("preparsed") is None

    def test_url_returns_images_for_image_content_type(self):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with patch("parse_recipe.fetch_url", return_value=(png_bytes, "image/png")):
            result = load_recipe_source("https://example.com/photo.png")

        assert result["images"] == [png_bytes]

    def test_url_pdf_content_type_converts_to_images(self):
        fake_page = MagicMock()
        fake_page.get_pixmap.return_value.tobytes.return_value = b"page_data"
        fake_doc = MagicMock()
        fake_doc.__iter__ = MagicMock(return_value=iter([fake_page]))

        with patch("parse_recipe.fetch_url", return_value=(b"%PDF-1.4 data", "application/pdf")), \
             patch("parse_recipe.fitz.open", return_value=fake_doc):
            result = load_recipe_source("https://example.com/recipe.pdf")

        assert result["images"] == [b"page_data"]

    def test_url_with_pdf_extension_converts_to_images(self):
        fake_doc = MagicMock()
        fake_doc.__iter__ = MagicMock(return_value=iter([]))

        with patch("parse_recipe.fetch_url", return_value=(b"%PDF data", "text/plain")), \
             patch("parse_recipe.fitz.open", return_value=fake_doc):
            result = load_recipe_source("https://example.com/menu.pdf")

        assert "images" in result

    def test_url_too_short_text_raises(self):
        sparse_html = b"<html><body><p>hi</p></body></html>"
        with patch("parse_recipe.fetch_url", return_value=(sparse_html, "text/html")):
            with pytest.raises(ValueError, match="enough text"):
                load_recipe_source("https://example.com/bad")


# ---------------------------------------------------------------------------
# load_recipe_source — local file branch
# ---------------------------------------------------------------------------

class TestLoadRecipeSourceLocal:
    def test_txt_file_returns_text(self, tmp_path):
        f = tmp_path / "recipe.txt"
        f.write_text("Chicken, garlic, cream. Mix and bake at 375F.", encoding="utf-8")
        result = load_recipe_source(str(f))
        assert result["text"] == "Chicken, garlic, cream. Mix and bake at 375F."

    def test_md_file_returns_text(self, tmp_path):
        f = tmp_path / "recipe.md"
        f.write_text("# My Recipe\n\n- Ingredient\n\n1. Step one.\n", encoding="utf-8")
        result = load_recipe_source(str(f))
        assert "# My Recipe" in result["text"]

    def test_empty_txt_raises(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_recipe_source(str(f))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_recipe_source(str(tmp_path / "nonexistent.pdf"))

    def test_image_file_returns_images(self, tmp_path):
        f = tmp_path / "recipe.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)  # minimal JPEG header
        result = load_recipe_source(str(f))
        assert isinstance(result["images"], list)
        assert len(result["images"]) == 1


# ---------------------------------------------------------------------------
# End-to-end: parse flow with mocked LLM
# ---------------------------------------------------------------------------

class TestEndToEndParseFlow:
    def test_txt_input_writes_output_files(self, tmp_path):
        recipe_txt = tmp_path / "my_recipe.txt"
        recipe_txt.write_text(
            "Ingredients: eggs, flour, sugar. Steps: mix, bake 30 min.", encoding="utf-8"
        )

        from parse_recipe import Ingredient
        mock_ingredients = [
            Ingredient(name="Egg", quantity="3", prep_note="", section="", optional=False),
            Ingredient(name="Flour", quantity="2 cups", prep_note="", section="", optional=False),
        ]
        mock_result = ("banana-cake", mock_ingredients, "1. Mix.\n2. Bake 30 min.")

        with patch("parse_recipe.parse_with_llm", return_value=mock_result):
            from parse_recipe import main
            import sys

            test_args = [
                "parse_recipe.py",
                str(recipe_txt),
                "--name", "banana-cake",
                "--data-dir", str(tmp_path / "out"),
            ]
            with patch.object(sys, "argv", test_args):
                main()

        import json as _json
        out_dir = tmp_path / "out" / "banana-cake"
        assert (out_dir / "ingredients.json").exists()
        assert (out_dir / "steps.md").exists()
        data = _json.loads((out_dir / "ingredients.json").read_text())
        assert any(i["name"] == "Egg" and i["quantity"] == "3" for i in data)
        assert "1. Mix." in (out_dir / "steps.md").read_text()

    def test_json_ld_url_skips_llm(self, tmp_path):
        """When JSON-LD is found, parse_with_llm must not be called."""
        html_bytes = SAMPLE_JSON_LD_HTML.encode()

        with patch("parse_recipe.fetch_url", return_value=(html_bytes, "text/html")), \
             patch("parse_recipe.parse_with_llm") as mock_llm:
            from parse_recipe import main
            import sys

            test_args = [
                "parse_recipe.py",
                "https://example.com/recipe",
                "--data-dir", str(tmp_path / "out"),
            ]
            with patch.object(sys, "argv", test_args):
                main()

        mock_llm.assert_not_called()
        out_dir = tmp_path / "out" / "classic-lasagna"
        assert (out_dir / "ingredients.json").exists()
