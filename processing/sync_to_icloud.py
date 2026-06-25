#!/usr/bin/env python3
"""Publish processed recipes to a shared iCloud Drive folder.

One-way push: copies a recipe's formatted output (ingredients.json + steps.md)
from data/recipes-formatted/<slug>/ into the iCloud folder so it syncs to other
devices/people. Runs on the Mac host (iCloud Drive is not available in Docker).

The iCloud destination is configured (no default) via, in priority order:
  1. --icloud-dir CLI argument
  2. RECIPE_ICLOUD_DIR environment variable (e.g. set in .env)
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Files copied for each recipe. Anything else in the slug dir is left alone.
SYNCED_FILES = ("ingredients.json", "steps.md")


def resolve_icloud_dir(cli_value: Optional[str]) -> Path:
    """Resolve the iCloud destination from the CLI arg or RECIPE_ICLOUD_DIR."""
    raw = cli_value or os.environ.get("RECIPE_ICLOUD_DIR")
    if not raw or not raw.strip():
        raise ValueError(
            "No iCloud folder configured. Set RECIPE_ICLOUD_DIR (e.g. in .env) "
            "or pass --icloud-dir '/path/to/iCloud Drive/Recipes'."
        )
    return Path(raw).expanduser()


def find_recipe_slugs(formatted_dir: Path) -> List[str]:
    if not formatted_dir.is_dir():
        return []
    return sorted(
        d.name
        for d in formatted_dir.iterdir()
        if d.is_dir() and (d / "ingredients.json").exists()
    )


def sync_recipe(
    slug: str,
    formatted_dir: Path,
    icloud_dir: Path,
    *,
    dry_run: bool = False,
) -> bool:
    """Copy one recipe's files into <icloud_dir>/<slug>/. Returns True if synced."""
    source_dir = formatted_dir / slug
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Recipe not found: {source_dir}")

    dest_dir = icloud_dir / slug
    logging.debug("Syncing '%s': %s → %s", slug, source_dir, dest_dir)
    files = [source_dir / name for name in SYNCED_FILES if (source_dir / name).exists()]
    if not files:
        raise FileNotFoundError(
            f"No syncable files ({', '.join(SYNCED_FILES)}) in {source_dir}"
        )

    if dry_run:
        logging.info("[dry-run] would copy %d file(s) → %s", len(files), dest_dir)
        for f in files:
            logging.info("[dry-run]   %s", f.name)
        return True

    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest_dir / f.name)
    logging.info("Synced '%s' (%d file(s)) → %s", slug, len(files), dest_dir)
    return True


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    default_data_dir = project_dir / "data"

    parser = argparse.ArgumentParser(
        description="Push processed recipes to a shared iCloud Drive folder."
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Recipe slug to sync (e.g. tuscan-chicken). Omit with --all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync every parsed recipe instead of a single slug.",
    )
    parser.add_argument(
        "--icloud-dir",
        help="Destination iCloud folder (overrides RECIPE_ICLOUD_DIR).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help=f"Base data directory (default: {default_data_dir})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing anything.",
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

    if not args.slug and not args.all:
        parser.error("Provide a recipe slug or --all.")
    if args.slug and args.all:
        parser.error("Provide either a slug or --all, not both.")

    try:
        icloud_dir = resolve_icloud_dir(args.icloud_dir)
    except ValueError as exc:
        logging.error("%s", exc)
        return 1

    formatted_dir = args.data_dir.expanduser().resolve() / "recipes-formatted"
    logging.debug("iCloud destination: %s | source: %s", icloud_dir, formatted_dir)

    if not args.dry_run and not icloud_dir.exists():
        logging.error(
            "iCloud folder does not exist: %s\n"
            "Create it (or open it once in Finder so iCloud Drive provisions it) and retry.",
            icloud_dir,
        )
        return 1

    if args.all:
        slugs = find_recipe_slugs(formatted_dir)
        if not slugs:
            logging.error("No parsed recipes found in %s", formatted_dir)
            return 1
        logging.info("Syncing %d recipe(s).", len(slugs))
    else:
        slugs = [args.slug]

    synced = 0
    failed = 0
    for slug in slugs:
        try:
            if sync_recipe(
                slug,
                formatted_dir,
                icloud_dir,
                dry_run=args.dry_run,
            ):
                synced += 1
        except (FileNotFoundError, OSError) as exc:
            failed += 1
            logging.error("Failed to sync '%s': %s", slug, exc)

    logging.info("Done: %d synced, %d failed", synced, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
