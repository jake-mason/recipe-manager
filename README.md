# Recipe Manager

Turn recipe photos, PDFs, text files, and **URLs** into structured markdown (ingredients + steps) using a local LLM, then push ingredients into the **Groceries** list in macOS Reminders (syncs to iOS via iCloud).

## What it does

The repo is split into two sections:

**Processing** (`processing/`) — turning input recipes into structured output:

1. **Parse** — Send an image, PDF, plain text file, or **http(s) URL** to [Ollama](https://ollama.com). Images and PDFs use a vision model; text files and web pages use a text model. Web pages with [schema.org](https://schema.org/Recipe) JSON-LD skip the LLM entirely.
2. **Publish (optional)** — Sync a processed recipe to a shared **iCloud Drive** folder so it's available on your other devices.

**Groceries** (`groceries/`) — using processed recipes:

3. **Search & import** — Run an interactive search over your parsed recipe library and add ingredients to the **Groceries** Reminders list in one step.

Parsing runs in Docker. Reminders import and iCloud sync run on the **Mac host** only (AppleScript and iCloud Drive aren't available inside a container).

### How the full pipeline runs

`./run_docker.sh <file> <slug> --groceries --sync` executes three stages **in order**, and only the first runs in a container:

| # | Stage | Where it runs | Script |
|---|-------|---------------|--------|
| 1 | **Parse** the recipe into `ingredients.json` + `steps.md` | Docker container (exits when done) | `processing/parse_recipe.py` |
| 2 | **Import** ingredients into the **Groceries** Reminders list (`--groceries`) | Mac host, after the container exits | `groceries/import_groceries.py` |
| 3 | **Sync** the output to your shared iCloud folder (`--sync`) | Mac host, after the container exits | `processing/sync_to_icloud.py` |

Reminders is **never** driven from inside Docker — `run_docker.sh` invokes `import_groceries.py` on the host after parsing finishes. Run the script as `./run_docker.sh …` (it's `#!/bin/bash` and uses bash arrays — don't invoke it with `sh`).

> **First-run note:** stage 2 calls `osascript`, which triggers a one-time macOS **Automation** permission prompt. If the run seems to hang right after parsing, look for that dialog (it can appear behind your editor) and click **Allow**. See [macOS Reminders setup](#macos-reminders-setup).

## Prerequisites

- **Docker** and **Docker Compose**
- Enough disk/RAM for Ollama and a vision model (default: `qwen2.5vl:3b`)
- **macOS** (for grocery import): Reminders app with a list named exactly **Groceries**, signed into the same iCloud account as your iPhone
- **fzf** (optional, recommended): `brew install fzf` — used by `groceries/pick_recipe.py` for live-filter search

## Quick start (Docker)

**Step 0 — one-time setup:**

```bash
# 1. Create your .env file (see Configuration below)

# 2. Make the wrapper executable
chmod +x run_docker.sh

# 3. Build the Docker image
docker compose build
```

Then parse a recipe:

```bash
./run_docker.sh /path/to/recipe.pdf tuscan-chicken
```

Output appears under `data/recipes-formatted/tuscan-chicken/`:

- `ingredients.json`
- `steps.md`

First run downloads the Ollama model and may take several minutes.

### Parse and import groceries in one step

```bash
./run_docker.sh /path/to/recipe.pdf tuscan-chicken --groceries
```

After parsing, this runs `groceries/import_groceries.py` on your Mac. Pass a **recipe name** when using `--groceries` so the correct folder is imported (otherwise the script uses the most recently modified folder under `data/recipes-formatted/`).

## Configuration

Create a `.env` file in the project root:

```env
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=qwen2.5vl:3b
```

| Variable | Purpose |
|----------|---------|
| `OLLAMA_HOST` | Ollama API URL. Use `http://ollama:11434` inside Docker Compose; use `http://localhost:11434` if running `parse_recipe.py` natively against a local Ollama instance. |
| `OLLAMA_MODEL` | Vision model tag for PDF/image extraction (and fallback for HTML/text). |
| `OLLAMA_TEXT_MODEL` | Optional text-only model for HTML pages and `.txt`/`.md` files (e.g. `qwen2.5:3b`). Defaults to `OLLAMA_MODEL` if unset. |
| `RECIPE_ICLOUD_DIR` | Optional. Destination folder for `sync_to_icloud.py` / `--sync`, e.g. `~/Library/Mobile Documents/com~apple~CloudDocs/Recipes`. No default — sync requires this (or `--icloud-dir`). |

## Project layout

The code is organized into two sections:

- **`processing/`** — turning input recipes into structured output.
- **`groceries/`** — selecting processed recipes and adding ingredients to the grocery list.

```
recipe-manager/
├── processing/
│   ├── parse_recipe.py          # Core parser (PDF/image/text/URL → structured output)
│   ├── batch_parse_recipes.py   # Batch-parse all files in recipes-unformatted/
│   └── sync_to_icloud.py        # Publish processed recipes to a shared iCloud folder (host only)
├── groceries/
│   ├── import_groceries.py      # macOS Reminders import (host only)
│   └── pick_recipe.py           # Interactive recipe search + grocery import
├── run_docker.sh            # Recommended entry point (Docker + optional --groceries / --sync)
├── docker-compose.yml       # Ollama + recipe parser service
├── Dockerfile
├── data/
│   ├── recipes-unformatted/ # Source files (PDF, images, .txt, .md, .docx, etc.)
│   └── recipes-formatted/   # Parser output (slug/ingredients.json, steps.md)
└── Makefile                 # docker-cleanup helper
```

Both directories are Python packages; the scripts run either as plain scripts (`python3 processing/parse_recipe.py`) or as modules (`python3 -m processing.parse_recipe`).

## Working with recipes

### Mode 1: Docker (recommended for parsing)

`run_docker.sh` starts Ollama, pulls the model if needed, builds the parser image, and runs one parse job.

```bash
./run_docker.sh <recipe_file_or_url> [recipe_name] [--groceries] [--sync]
```

| Argument | Description |
|----------|-------------|
| `recipe_file_or_url` | Path to a **PDF**, **image**, **`.txt`/`.md`**, or **document** (`.docx`, `.odt`, `.rtf`, `.epub`, `.html`, …) file, or an **http(s) URL** |
| `recipe_name` | Optional slug (e.g. `tuscan-chicken`). Overrides the LLM-generated name. |
| `--groceries` | After a successful parse, import ingredients into Reminders on the Mac |
| `--sync` | After a successful parse, publish the recipe to the shared iCloud folder (needs `RECIPE_ICLOUD_DIR`) |

**Examples:**

```bash
./run_docker.sh ~/Downloads/lasagna.pdf lasagna
./run_docker.sh ~/Pictures/recipe-card.jpg
./run_docker.sh data/recipes-unformatted/hot_dagos_v2.txt hot-dagos
./run_docker.sh "https://www.example.com/recipe/print/" honey-garlic-chicken
./run_docker.sh data/recipes-unformatted/Honey_Garlic_Chicken.pdf honey-garlic-chicken --groceries
```

**Stop background services:**

```bash
docker compose down
```

**Full cleanup** (containers, volumes, built image):

```bash
make docker-cleanup
```

#### Running other scripts in the container

The image's entrypoint is `bash`. Both `processing/` and `groceries/` are copied
in, so you can run any bundled script with `bash -c "python3 …"`, or drop into a
shell and work interactively. Running the service with no command opens a shell.

```bash
# Drop into an interactive shell (bash is the entrypoint)
docker compose run --rm recipe-manager-app

# Parse a single recipe
docker compose run --rm recipe-manager-app -c "python3 processing/parse_recipe.py /input/recipe.pdf --name my-slug"

# Batch-parse everything in data/recipes-unformatted/
docker compose run --rm recipe-manager-app -c "python3 processing/batch_parse_recipes.py --dry-run"

# Run an arbitrary module or one-off snippet
docker compose run --rm recipe-manager-app -c "python3 -m processing.parse_recipe --help"
docker compose run --rm recipe-manager-app -c "python3 -c 'import sys; print(sys.version)'"
```

Note that `groceries/import_groceries.py` and `processing/sync_to_icloud.py` rely
on macOS-only facilities (AppleScript, iCloud Drive) and are meant to run on the
Mac host, not inside the container.

### Mode 2: Batch parse everything

Parse all supported files in `data/recipes-unformatted/` in one shot:

```bash
python3 processing/batch_parse_recipes.py [--dry-run] [--fail-fast] [--groceries] [--sync]
```

Supported formats: PDF, JPEG, PNG, GIF, WEBP, HEIC, TXT, MD. Pass `--sync` to publish each parsed recipe to the shared iCloud folder.

### Mode 3: Native Python (no Docker)

Use this if Ollama is already running on your Mac.

```bash
pip install -r requirements.txt
export OLLAMA_HOST=http://localhost:11434

python3 processing/parse_recipe.py /path/to/recipe.pdf --name tuscan-chicken
python3 processing/parse_recipe.py data/recipes-unformatted/hot_dagos_v2.txt --name hot-dagos
python3 processing/parse_recipe.py "https://www.example.com/recipe/print/" --name tuscan-chicken
```

| Flag | Description |
|------|-------------|
| `--name` | Recipe slug for the output folder |
| `--data-dir` | Base output directory (default: `data/recipes-formatted`) |
| `--model` | Ollama model tag (default: `OLLAMA_MODEL` or `qwen2.5vl:3b`) |
| `--import-groceries` | After writing files, import into Reminders (macOS only) |

### Mode 4: Interactive search + grocery import

Search your parsed recipe library and add ingredients to Reminders in one command:

```bash
python3 groceries/pick_recipe.py
```

If [fzf](https://github.com/junegunn/fzf) is installed, you get a live-filter search — type to narrow, arrow keys to navigate, Enter to select. Without fzf, it falls back to a simple text filter and numbered list.

```bash
python3 groceries/pick_recipe.py --dry-run        # preview ingredients without touching Reminders
python3 groceries/pick_recipe.py --list "Shopping List"  # use a different Reminders list
```

### Mode 5: Grocery import only

Use this when you already have parsed `ingredients.json` files and only need Reminders updated.

```bash
# By recipe slug
python3 groceries/import_groceries.py tuscan-chicken

# By explicit file or recipe directory
python3 groceries/import_groceries.py --file data/recipes-formatted/tuscan-chicken/ingredients.json
python3 groceries/import_groceries.py --file data/recipes-formatted/tuscan-chicken
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Print ingredient lines without touching Reminders |
| `--note` | Set the reminder body (default for slug import: `from <slug>`) |
| `--list` | Reminders list name (default: `Groceries`) |
| `--data-dir` | Base `data/` directory for slug lookup |

### Mode 6: Publish to a shared iCloud folder

Push a processed recipe's structured output (`ingredients.json` + `steps.md`) into a shared folder in iCloud Drive so it syncs to your other devices or people you share the folder with. Runs on the **Mac host** (iCloud Drive isn't available inside Docker).

Set the destination once in `.env`:

```env
RECIPE_ICLOUD_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/Recipes
```

Then:

```bash
# Sync a single recipe
python3 processing/sync_to_icloud.py tuscan-chicken

# Or override the destination per-run
python3 processing/sync_to_icloud.py tuscan-chicken --icloud-dir "~/Library/Mobile Documents/com~apple~CloudDocs/Recipes"

# Sync the whole library; preview first
python3 processing/sync_to_icloud.py --all --dry-run
```

Or do it automatically right after parsing with `--sync` (see Modes 1 and 2):

```bash
./run_docker.sh ~/Downloads/lasagna.pdf lasagna --sync
```

| Flag | Description |
|------|-------------|
| `slug` / `--all` | A single recipe slug, or `--all` for every parsed recipe |
| `--icloud-dir` | Destination folder (overrides `RECIPE_ICLOUD_DIR`) |
| `--dry-run` | Show what would be copied without writing |
| `--data-dir` | Base `data/` directory for source lookup |

## Output format

Each parsed recipe gets its own directory:

```
data/recipes-formatted/<recipe-slug>/
├── ingredients.json  # Structured ingredients (name, quantity, prep_note, section, optional)
└── steps.md          # Markdown instructions
```

`groceries/import_groceries.py` reads `ingredients.json`: each entry becomes one Reminders title (`name (quantity)`), tagged with the recipe slug and any section as `#tags`. Items marked `optional` are skipped unless `--include-optional` is passed.

## Supported inputs

| Format | Parse support |
|--------|----------------|
| PDF (file or URL) | Yes — each page rendered to an image for the vision model |
| Images (JPEG, PNG, HEIC, etc.; file or URL) | Yes — vision model |
| Plain text (`.txt`, `.md`) | Yes — sent as text to the LLM |
| Documents (`.docx`, `.odt`, `.rtf`, `.epub`, `.html`/`.htm`, `.rst`, `.org`, `.tex`, `.textile`, `.fb2`, `.docbook`) | Yes — converted to markdown via `pandoc`, then sent as text to the LLM |
| Recipe web pages (`http`/`https`) | Yes — JSON-LD `Recipe` schema when present; otherwise main text via trafilatura + text LLM |

For URLs, use the site's **print** or **print-friendly** link when available (fewer ads and sidebars).

Document formats require the [`pandoc`](https://pandoc.org/) binary on your PATH. Install it with `brew install pandoc` (macOS) or `apt-get install pandoc` (Linux). It is already installed in the Docker image, so no extra setup is needed for Docker-based parsing.

## macOS Reminders setup

1. Open **Reminders** and create or confirm a list named **Groceries** (must match exactly unless you pass `--list`).
2. Sign in to iCloud on Mac and iPhone so lists sync.
3. On first import, macOS may prompt for **Automation** permission — allow your terminal app (Terminal, iTerm, or Cursor) to control **Reminders**.

If import fails with `Not authorized to send Apple events to Reminders`, enable access under **System Settings → Privacy & Security → Automation**.

Items created on the Mac should appear on iPhone in **Reminders → Groceries** after iCloud sync (usually seconds).

## Typical workflows

**New recipe from a photo or PDF:**

```bash
./run_docker.sh ~/Downloads/recipe-scan.pdf my-recipe --groceries
```

**New recipe from a text file:**

```bash
./run_docker.sh data/recipes-unformatted/my-recipe.txt my-recipe
```

**Spin up and shop from existing recipes:**

```bash
python3 groceries/pick_recipe.py
```

**Parse everything in the unformatted folder:**

```bash
python3 processing/batch_parse_recipes.py
```

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| Model download slow or fails | Ensure Docker has network access; run `docker compose exec ollama ollama pull <model>` manually |
| Parser cannot reach Ollama | In Docker, `OLLAMA_HOST` must be `http://ollama:11434`, not `localhost` |
| Empty or bad extraction | Try a clearer scan or the print URL; use `--name` for a stable folder; try a different `--model` or set `OLLAMA_TEXT_MODEL` for HTML/text |
| URL fetch fails or 403 | Site may block bots; try saving as PDF and parsing the file instead |
| Command seems to hang right after parsing | Stage 2 (grocery import) is waiting on the macOS **Automation** permission dialog — look for it (it can hide behind your editor) and click **Allow**. It runs on the host, not in Docker. |
| Grocery import finds wrong recipe | Pass the slug explicitly; use `--file` pointing at the right `ingredients.json` |
| `--groceries` cannot resolve slug | Always pass `recipe_name` as the second argument to `run_docker.sh` |
| `groceries/pick_recipe.py` shows no recipes | Parse some recipes first — they must exist under `data/recipes-formatted/` |

## Dependencies

**Parser** (`requirements.txt`): PyMuPDF, ollama, pydantic, python-dotenv, requests, trafilatura, beautifulsoup4

**Grocery import / picker**: Python 3.9+ standard library only (`osascript` on macOS); `fzf` optional for `groceries/pick_recipe.py`
