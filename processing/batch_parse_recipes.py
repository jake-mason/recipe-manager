#!/usr/bin/env python3
"""Run run_docker.sh for each PDF/image in data/recipes-unformatted/."""

import argparse
import logging
import re
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".txt", ".md"}

def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    words = [w for w in slug.split("-") if w][:4]
    return "-".join(words) if words else "unknown-recipe"


def discover_recipe_files(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    files = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def run_docker(
    project_dir: Path,
    file_path: Path,
    slug: str,
    *,
    dry_run: bool,
    groceries: bool,
    sync: bool,
) -> int:
    cmd = [str(project_dir / "run_docker.sh"), str(file_path.resolve()), slug]
    if groceries:
        cmd.append("--groceries")
    if sync:
        cmd.append("--sync")

    display = " ".join(cmd)
    if dry_run:
        logging.info("[dry-run] %s", display)
        return 0

    logging.info("Running: %s", display)
    result = subprocess.run(cmd, cwd=project_dir)
    return result.returncode


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    default_input_dir = project_dir / "data" / "recipes-unformatted"

    parser = argparse.ArgumentParser(
        description="Parse every PDF/image in recipes-unformatted via run_docker.sh."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=default_input_dir,
        help=f"Directory of source recipe files (default: {default_input_dir})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print run_docker.sh commands without executing them.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed recipe.",
    )
    parser.add_argument(
        "--groceries",
        action="store_true",
        help="Pass --groceries to each run_docker.sh invocation.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Pass --sync to each run_docker.sh invocation (push results to iCloud).",
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

    input_dir = args.input_dir.expanduser().resolve()

    try:
        recipe_files = discover_recipe_files(input_dir)
    except FileNotFoundError as exc:
        logging.error("%s", exc)
        return 1

    if not recipe_files:
        logging.error("No parseable files found in %s", input_dir)
        logging.error("Supported extensions: %s", ", ".join(sorted(SUPPORTED_EXTENSIONS)))
        return 1

    logging.info("Found %d recipe file(s) in %s", len(recipe_files), input_dir)

    succeeded = 0
    failed = 0

    for index, file_path in enumerate(recipe_files, 1):
        slug = slugify(file_path.stem)
        logging.info("[%d/%d] %s → slug '%s'", index, len(recipe_files), file_path.name, slug)
        exit_code = run_docker(
            project_dir,
            file_path,
            slug,
            dry_run=args.dry_run,
            groceries=args.groceries,
            sync=args.sync,
        )
        if exit_code == 0:
            succeeded += 1
        else:
            failed += 1
            logging.error("Failed (%d): %s", exit_code, file_path.name)
            if args.fail_fast:
                break

    logging.info("Done: %d succeeded, %d failed", succeeded, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
