#!/usr/bin/env python3
"""Interactive recipe picker — search parsed recipes and add ingredients to Groceries."""

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Allow running as a plain script (python groceries/pick_recipe.py) while still
# resolving the `groceries` package via absolute imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def find_recipes(data_dir: Path) -> list[str]:
    formatted = data_dir / "recipes-formatted"
    if not formatted.is_dir():
        return []
    return sorted(
        d.name
        for d in formatted.iterdir()
        if d.is_dir() and (d / "ingredients.json").exists()
    )


def pick_with_fzf(recipes: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["fzf", "--prompt", "Recipe > ", "--height", "~50%", "--reverse", "--info=hidden"],
            input="\n".join(recipes),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None  # user cancelled (ESC / Ctrl-C)
    except FileNotFoundError:
        return "FZF_NOT_FOUND"


def pick_with_fallback(recipes: list[str]) -> Optional[str]:
    """Filter-then-number picker used when fzf is unavailable."""
    query = input("Search recipes (leave blank to list all): ").strip().lower()
    matches = [r for r in recipes if query in r] if query else list(recipes)

    if not matches:
        print(f"No recipes match '{query}'.")
        return None

    if len(matches) == 1:
        confirm = input(f"Select '{matches[0]}'? [Y/n] ").strip().lower()
        return matches[0] if confirm in ("", "y", "yes") else None

    for i, name in enumerate(matches, 1):
        print(f"  {i:2}. {name}")

    choice = input(f"Pick [1-{len(matches)}]: ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(matches):
            return matches[idx]
    except ValueError:
        pass

    print("Invalid selection.")
    return None


def pick_recipe(recipes: list[str]) -> Optional[str]:
    selection = pick_with_fzf(recipes)
    if selection == "FZF_NOT_FOUND":
        print("Tip: install fzf for a better search experience:  brew install fzf\n")
        selection = pick_with_fallback(recipes)
    return selection


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    default_data_dir = project_dir / "data"

    parser = argparse.ArgumentParser(
        description="Search parsed recipes and add ingredients to macOS Reminders."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help=f"Base data directory (default: {default_data_dir})",
    )
    parser.add_argument(
        "--list",
        default="Groceries",
        help="Reminders list name (default: Groceries)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip items already present in the Reminders list.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ingredients without adding to Reminders.",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.expanduser().resolve()
    recipes = find_recipes(data_dir)

    if not recipes:
        logging.error("No parsed recipes found in %s/recipes-formatted/", data_dir)
        logging.error("Parse some recipes first with run_docker.sh or parse_recipe.py.")
        return 1

    slug = pick_recipe(recipes)
    if not slug:
        print("No recipe selected.")
        return 0

    from groceries.import_groceries import add_to_reminders, parse_ingredients_json, resolve_ingredients_file

    try:
        ingredients_path = resolve_ingredients_file(slug, None, data_dir)
        items = parse_ingredients_json(ingredients_path)
        logging.info("Found %d ingredient(s) in '%s'.", len(items), slug)
        add_to_reminders(
            items,
            list_name=args.list,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            note=f"from {slug}",
        )
        return 0
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
