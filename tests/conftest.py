"""Shared fixtures for the recipe-manager test suite."""

import pytest
from pathlib import Path


@pytest.fixture()
def recipe_data_dir(tmp_path: Path) -> Path:
    """Create a minimal data/ layout with one parsed recipe."""
    slug = "tuscan-chicken"
    recipe_dir = tmp_path / "recipes-formatted" / slug
    recipe_dir.mkdir(parents=True)

    import json
    (recipe_dir / "ingredients.json").write_text(
        json.dumps([
            {"name": "Chicken breast", "quantity": "1 lb", "prep_note": "", "section": "", "optional": False},
            {"name": "Garlic", "quantity": "3 cloves", "prep_note": "", "section": "", "optional": False},
            {"name": "Heavy cream", "quantity": "1 cup", "prep_note": "", "section": "SAUCE", "optional": False},
            {"name": "Sun-dried tomatoes", "quantity": "1/2 cup", "prep_note": "", "section": "SAUCE", "optional": False},
        ], indent=2),
        encoding="utf-8",
    )
    (recipe_dir / "steps.md").write_text(
        "# Steps\n\n1. Season chicken.\n2. Sear in oil.\n3. Add sauce.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def ingredients_json_path(recipe_data_dir: Path) -> Path:
    return recipe_data_dir / "recipes-formatted" / "tuscan-chicken" / "ingredients.json"


SAMPLE_JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Classic Lasagna",
  "recipeIngredient": ["Lasagna noodles (12)", "Ricotta cheese (2 cups)", "Mozzarella (3 cups)"],
  "recipeInstructions": [
    {"@type": "HowToStep", "text": "Boil noodles until al dente."},
    {"@type": "HowToStep", "text": "Layer with cheese and sauce."},
    {"@type": "HowToStep", "text": "Bake at 375F for 45 minutes."}
  ]
}
</script>
</head><body><p>A great lasagna recipe.</p></body></html>
"""

SAMPLE_PLAIN_HTML = """
<html><body>
<article>
<h1>Simple Pasta</h1>
<p>Ingredients: pasta, olive oil, garlic.</p>
<p>Instructions: Boil pasta. Fry garlic in oil. Combine.</p>
</article>
</body></html>
"""
