#!/usr/bin/env python3
"""Import parsed recipe ingredients into macOS Reminders (Groceries list)."""

import argparse
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_LIST_NAME = "Groceries"


@dataclass
class IngredientItem:
    name: str
    tag_names: list[str] = field(default_factory=list)
    note: Optional[str] = None


def _to_tag_name(s: str) -> str:
    """Sanitize a string into a valid Reminders tag name (lowercase, hyphens only)."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_ingredients_json(
    path: Path,
    include_optional: bool = False,
    recipe_name: Optional[str] = None,
) -> list[IngredientItem]:
    """Load ingredients.json and return structured IngredientItems with Reminders tags."""
    if recipe_name is None:
        recipe_name = path.parent.name
    recipe_tag = _to_tag_name(recipe_name)

    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for item in data:
        if item.get("optional") and not include_optional:
            continue
        name = item.get("name", "").strip()
        if not name:
            continue
        quantity = item.get("quantity", "").strip()
        section = item.get("section", "").strip()
        display_name = f"{name} ({quantity})" if quantity else name
        tags = [recipe_tag]
        if section:
            tags.append(_to_tag_name(section))
        items.append(IngredientItem(name=display_name, tag_names=tags))
    return items


def resolve_ingredients_file(
    slug: Optional[str],
    file_path: Optional[Path],
    data_dir: Path,
) -> Path:
    """Resolve slug or explicit file path to an ingredients.json path."""
    if file_path is not None:
        path = file_path.expanduser().resolve()
        if path.is_dir():
            path = path / "ingredients.json"
        if not path.exists():
            raise FileNotFoundError(f"Ingredients file not found: {path}")
        return path

    if not slug:
        raise ValueError("Recipe slug or --file is required.")

    candidates = [
        data_dir / "recipes-formatted" / slug / "ingredients.json",
        data_dir / slug / "ingredients.json",
    ]
    for path in candidates:
        if path.exists():
            return path

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"No ingredients.json found for '{slug}'. Tried: {searched}")


def _applescript_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise OSError("Reminders import requires macOS (osascript is unavailable).")


def _run_osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "osascript failed"
        raise RuntimeError(stderr)
    return result.stdout.strip()


def _verify_list_exists(list_name: str) -> None:
    script = f"""
    tell application "Reminders"
        if not (exists list "{_applescript_escape(list_name)}") then
            error "Reminders list not found: {list_name}"
        end if
    end tell
    """
    _run_osascript(script)


def get_existing_reminder_names(list_name: str) -> Set[str]:
    script = f"""
    tell application "Reminders"
        tell list "{_applescript_escape(list_name)}"
            set out to ""
            repeat with r in reminders
                set out to out & (name of r) & linefeed
            end repeat
            return out
        end tell
    end tell
    """
    output = _run_osascript(script)
    if not output:
        return set()
    names = {line.strip() for line in output.splitlines() if line.strip()}
    return {name.casefold() for name in names}


def _make_reminder_statement(item: IngredientItem, note: Optional[str]) -> str:
    name_esc = _applescript_escape(item.name)
    parts = []
    if item.tag_names:
        parts.append(" ".join(f"#{t}" for t in item.tag_names))
    if note or item.note:
        parts.append(note or item.note)  # type: ignore[arg-type]
    body = "\n".join(parts) if parts else None
    props = [f'name:"{name_esc}"']
    if body:
        props.append(f'body:"{_applescript_escape(body)}"')
    return f"make new reminder with properties {{{', '.join(props)}}}"


def add_to_reminders(
    items: list[IngredientItem],
    list_name: str = DEFAULT_LIST_NAME,
    skip_existing: bool = False,
    dry_run: bool = False,
    note: Optional[str] = None,
) -> int:
    """Add items to a Reminders list. Returns the number of reminders created."""
    if not items:
        logging.warning("No ingredients to import.")
        return 0

    if dry_run:
        logging.info("Dry run — would add %d item(s) to '%s':", len(items), list_name)
        for item in items:
            tag_str = "  " + " ".join(f"#{t}" for t in item.tag_names) if item.tag_names else ""
            print(f"{item.name}{tag_str}")
        return 0

    _require_macos()
    _verify_list_exists(list_name)

    to_add = items
    if skip_existing:
        existing = get_existing_reminder_names(list_name)
        to_add = [item for item in items if item.name.casefold() not in existing]
        skipped = len(items) - len(to_add)
        if skipped:
            logging.info("Skipping %d existing item(s).", skipped)
        if not to_add:
            logging.info("All items already exist in '%s'.", list_name)
            return 0

    statements = "\n            ".join(
        _make_reminder_statement(item, note) for item in to_add
    )
    script = f"""
    tell application "Reminders"
        tell list "{_applescript_escape(list_name)}"
            {statements}
        end tell
    end tell
    """

    _run_osascript(script)
    logging.info("Added %d item(s) to '%s'.", len(to_add), list_name)
    return len(to_add)


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    default_data_dir = project_dir / "data"

    parser = argparse.ArgumentParser(
        description="Import parsed recipe ingredients into macOS Reminders (Groceries list)."
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Recipe slug (e.g. tuscan-chicken). Resolves under data/recipes-formatted/ or data/.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Path to ingredients.json or a recipe directory containing it.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help=f"Base data directory for slug lookup (default: {default_data_dir})",
    )
    parser.add_argument(
        "--list",
        default=DEFAULT_LIST_NAME,
        help=f"Reminders list name (default: {DEFAULT_LIST_NAME})",
    )
    parser.add_argument(
        "--note",
        help="Optional reminder body text applied to all imported items.",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Include ingredients marked optional (skipped by default).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip items whose names already exist in the list (case-insensitive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print items without creating reminders.",
    )
    args = parser.parse_args()

    if not args.slug and not args.file:
        parser.error("Provide a recipe slug or --file path.")

    try:
        ingredients_path = resolve_ingredients_file(
            args.slug,
            args.file,
            args.data_dir.resolve(),
        )
        items = parse_ingredients_json(
            ingredients_path,
            include_optional=args.include_optional,
            recipe_name=args.slug,
        )
        logging.info("Read %d ingredient(s) from %s", len(items), ingredients_path)
        add_to_reminders(
            items,
            list_name=args.list,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            note=args.note,
        )
        return 0
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
