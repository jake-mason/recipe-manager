# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Parses recipe files (PDF, image) or URLs into structured markdown (ingredients + steps) using a local LLM via Ollama, then optionally pushes ingredients into the macOS Reminders app (syncs to iOS) and/or publishes the processed output to a shared iCloud Drive folder.

The code is split into two sections:
- **`processing/`** — generating structured recipes from input (`parse_recipe.py`, `batch_parse_recipes.py`, `sync_to_icloud.py`).
- **`groceries/`** — selecting processed recipes and adding ingredients to the grocery list (`import_groceries.py`, `pick_recipe.py`).

Both are Python packages (each has `__init__.py`). Scripts use absolute imports (e.g. `from groceries.import_groceries import ...`) and insert the repo root onto `sys.path` so they also work when run as plain scripts (`python3 processing/parse_recipe.py`).

## Common commands

```bash
# Parse a single recipe via Docker (recommended)
./run_docker.sh /path/to/recipe.pdf [recipe-slug] [--groceries] [--sync]

# Parse all files in data/recipes-unformatted/ via Docker
python3 processing/batch_parse_recipes.py [--dry-run] [--fail-fast] [--groceries] [--sync]

# Parse natively (requires local Ollama at localhost:11434)
export OLLAMA_HOST=http://localhost:11434
python3 processing/parse_recipe.py /path/to/recipe.pdf --name my-slug [--import-groceries]

# Publish a processed recipe to the shared iCloud folder (macOS host, no Docker)
python3 processing/sync_to_icloud.py <recipe-slug>          # needs RECIPE_ICLOUD_DIR or --icloud-dir
python3 processing/sync_to_icloud.py --all --dry-run
python3 processing/sync_to_icloud.py <slug> --icloud-dir "~/Library/Mobile Documents/com~apple~CloudDocs/Recipes"

# Interactive recipe search + import to Reminders (uses fzf if installed, else text fallback)
python3 groceries/pick_recipe.py [--dry-run] [--list <name>]

# Import ingredients into Reminders only (macOS host, no Docker)
python3 groceries/import_groceries.py <recipe-slug>
python3 groceries/import_groceries.py --file data/recipes-formatted/<slug>/ingredients.md
python3 groceries/import_groceries.py <slug> --dry-run

# Docker maintenance
docker compose down          # stop background services
make docker-cleanup          # full teardown: containers, volumes, images
```

## Architecture

**Parse pipeline** (`processing/parse_recipe.py`):
1. `load_recipe_source()` — loads input as images (PDF→PNG pages via PyMuPDF, or raw image bytes) or text (URL HTML via trafilatura/BeautifulSoup; document files like `.docx`/`.odt`/`.rtf`/`.epub`/`.html` are converted to markdown via `convert_with_pandoc`, which shells out to the `pandoc` binary). URLs with schema.org JSON-LD Recipe data skip the LLM entirely (`recipe_from_json_ld`).
2. `parse_with_llm()` — sends images or text to Ollama (or the Anthropic API when `USE_ANTHROPIC=true`); response is structured via `RecipeStructure` (Pydantic).
3. `write_recipe_output()` — writes `data/recipes-formatted/<slug>/ingredients.json` and `steps.md`.

**iCloud publish** (`processing/sync_to_icloud.py`):
- Runs on the **Mac host only** — iCloud Drive is not mounted in Docker.
- One-way push: copies `ingredients.json` + `steps.md` from `data/recipes-formatted/<slug>/` to `<RECIPE_ICLOUD_DIR>/<slug>/`. Destination comes from `--icloud-dir` or the `RECIPE_ICLOUD_DIR` env var (no default).

**Grocery import** (`groceries/import_groceries.py`):
- Runs on the **Mac host only** — uses `osascript` to drive the Reminders app via AppleScript. Cannot run inside Docker.
- `parse_ingredients_json()` reads the structured ingredients and builds Reminders titles + `#tags`.
- `add_to_reminders()` batches all items into a single AppleScript block.

**Docker split**: Parsing runs in a container (`recipe-manager-app` service in docker-compose.yml, entrypoint `processing/parse_recipe.py`) alongside an `ollama` service. The `run_docker.sh` script handles model pulling, volume mounts, and post-parse grocery import / iCloud sync on the Mac host (`--groceries`, `--sync`).

**Name resolution**: Recipe slug priority is `--name` CLI arg → `RECIPE_NAME` env var → LLM-inferred `recipe_name_slug` field.

## Configuration

`.env` in project root (required for Docker mode):
```env
OLLAMA_HOST=http://ollama:11434   # use http://localhost:11434 for native
OLLAMA_MODEL=qwen2.5vl:3b        # vision model (default)
OLLAMA_TEXT_MODEL=qwen2.5:3b     # optional: text-only model for HTML pages
RECIPE_ICLOUD_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/Recipes  # optional: iCloud publish target for sync_to_icloud.py / --sync
```

## Data layout

```
data/
├── recipes-unformatted/   # source PDFs, images, etc. (input for batch_parse_recipes.py)
└── recipes-formatted/
    └── <slug>/
        ├── ingredients.json
        └── steps.md
```

`.txt` and `.md` files are passed as plain text directly to the LLM (no vision model). Document formats in `PANDOC_EXTENSIONS` (`.docx`, `.odt`, `.rtf`, `.epub`, `.html`/`.htm`, `.rst`, `.org`, `.tex`, `.textile`, `.fb2`, `.docbook`) are converted to markdown via the `pandoc` binary and then sent as text (no vision model). PDF and images are rendered as PNG pages via PyMuPDF before sending to the vision model.

`pandoc` must be on PATH for the document formats above (`brew install pandoc` on the Mac host; it is installed in the Docker image). If it is missing, `convert_with_pandoc` raises a clear error.

## macOS Reminders setup

The Reminders list must be named **Groceries** exactly (or pass `--list`). On first use, macOS will prompt for Automation permission — grant it under System Settings → Privacy & Security → Automation for your terminal app.
