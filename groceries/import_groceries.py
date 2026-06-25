#!/usr/bin/env python3
"""Import parsed recipe ingredients into macOS Reminders (Groceries list)."""

import argparse
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_LIST_NAME = "Groceries"

# osascript blocks on the first-run macOS Automation permission dialog. Cap the
# wait so a missed/unanswered prompt fails fast with guidance instead of hanging.
OSASCRIPT_TIMEOUT_SECONDS = 60


@dataclass
class IngredientItem:
    name: str
    recipe_name: str = ""
    section: str = ""


def _simplify_section(section: str) -> str:
    """Strip common lead-in phrases from section names ('For the Grits' → 'Grits')."""
    return re.sub(r"(?i)^(for\s+the\s+|for\s+|the\s+)", "", section).strip()


def parse_ingredients_json(
    path: Path,
    include_optional: bool = False,
    recipe_name: Optional[str] = None,
) -> list[IngredientItem]:
    """Load ingredients.json and return structured IngredientItems."""
    if recipe_name is None:
        recipe_name = path.parent.name
    # Convert slug to human-readable name (e.g. "shrimp-and-grits" → "Shrimp and Grits")
    _lowercase_words = {"a", "an", "and", "as", "at", "but", "by", "for", "in",
                        "nor", "of", "on", "or", "so", "the", "to", "up", "yet"}
    words = recipe_name.replace("-", " ").split()
    display_recipe_name = " ".join(
        w if (i > 0 and w in _lowercase_words) else w.capitalize()
        for i, w in enumerate(words)
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    seen: Set[tuple] = set()
    for item in data:
        if item.get("optional") and not include_optional:
            continue
        name = item.get("name", "").strip()
        if not name:
            continue
        quantity = item.get("quantity", "").strip()
        section = _simplify_section(item.get("section", "").strip())
        display_name = f"{name} ({quantity})" if quantity else name
        key = (name.casefold(), quantity.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append(IngredientItem(name=display_name, recipe_name=display_recipe_name, section=section))
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
        logging.debug("Looking for ingredients at %s", path)
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
    logging.debug("Running osascript:\n%s", script)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"osascript timed out after {OSASCRIPT_TIMEOUT_SECONDS}s. This usually means "
            "the macOS Automation permission prompt is waiting for a response — look for "
            "the dialog (it can hide behind your editor) and click Allow, or grant access "
            "under System Settings → Privacy & Security → Automation, then re-run."
        )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "osascript failed"
        logging.debug("osascript exited %d: %s", result.returncode, stderr)
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


def _make_reminder_statement(item: IngredientItem) -> str:
    name_esc = _applescript_escape(item.name)
    note_parts = [item.recipe_name] if item.recipe_name else []
    if item.section:
        note_parts.append(item.section)
    body = " | ".join(note_parts) or None
    props = [f'name:"{name_esc}"']
    if body:
        props.append(f'body:"{_applescript_escape(body)}"')
    return f"make new reminder with properties {{{', '.join(props)}}}"


def add_to_reminders(
    items: list[IngredientItem],
    list_name: str = DEFAULT_LIST_NAME,
    dry_run: bool = False,
) -> int:
    """Add items to a Reminders list, skipping any that already exist.

    Returns the number of reminders created.
    """
    if not items:
        logging.warning("No ingredients to import.")
        return 0

    if dry_run:
        logging.info("Dry run — would add %d item(s) to '%s':", len(items), list_name)
        for item in items:
            note_parts = [item.recipe_name] if item.recipe_name else []
            if item.section:
                note_parts.append(item.section)
            note_str = f"  ({' | '.join(note_parts)})" if note_parts else ""
            print(f"{item.name}{note_str}")
        return 0

    _require_macos()
    _verify_list_exists(list_name)
    logging.info("Machine setup looks fine")

    existing = get_existing_reminder_names(list_name)
    to_add = [item for item in items if item.name.casefold() not in existing]
    skipped = len(items) - len(to_add)
    if skipped:
        logging.info("Skipping %d existing item(s).", skipped)
    if not to_add:
        logging.info("All items already exist in '%s'.", list_name)
        return 0

    statements = "\n            ".join(
        _make_reminder_statement(item) for item in to_add
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
        "--include-optional",
        action="store_true",
        help="Include ingredients marked optional (skipped by default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print items without creating reminders.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Verbose logging enabled.")

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
            dry_run=args.dry_run,
        )
        return 0
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
