# Recipe Manager

Turn recipe photos, PDFs, text files, and **URLs** into structured markdown (ingredients + steps) using a local LLM, then push ingredients into the **Groceries** list in macOS Reminders (syncs to iOS via iCloud).

## What it does

1. **Parse** — Send an image, PDF, plain text file, or **http(s) URL** to [Ollama](https://ollama.com). Images and PDFs use a vision model; text files and web pages use a text model. Web pages with [schema.org](https://schema.org/Recipe) JSON-LD skip the LLM entirely.
2. **Search & import** — Run an interactive search over your parsed recipe library and add ingredients to the **Groceries** Reminders list in one step.

Parsing runs in Docker. Reminders import runs on the **Mac host** only (AppleScript cannot run inside a container).

## Prerequisites

- **Docker** and **Docker Compose**
- Enough disk/RAM for Ollama and a vision model (default: `qwen2.5vl:3b`)
- **macOS** (for grocery import): Reminders app with a list named exactly **Groceries**, signed into the same iCloud account as your iPhone
- **fzf** (optional, recommended): `brew install fzf` — used by `pick_recipe.py` for live-filter search

## Quick start (Docker)

```bash
# From the project root — create .env first (see Configuration)
chmod +x run_docker.sh
./run_docker.sh /path/to/recipe.pdf tuscan-chicken
```

Output appears under `data/recipes-formatted/tuscan-chicken/`:

- `ingredients.md`
- `steps.md`

First run downloads the Ollama model and may take several minutes.

### Parse and import groceries in one step

```bash
./run_docker.sh /path/to/recipe.pdf tuscan-chicken --groceries
```

After parsing, this runs `import_groceries.py` on your Mac. Pass a **recipe name** when using `--groceries` so the correct folder is imported (otherwise the script uses the most recently modified folder under `data/recipes-formatted/`).

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

## Project layout

```
recipe-manager/
├── parse_recipe.py          # Core parser (PDF/image/text/URL → markdown)
├── import_groceries.py      # macOS Reminders import (host only)
├── pick_recipe.py           # Interactive recipe search + grocery import
├── batch_parse_recipes.py   # Batch-parse all files in recipes-unformatted/
├── run_docker.sh            # Recommended entry point (Docker + optional groceries)
├── docker-compose.yml       # Ollama + one-shot parser service
├── Dockerfile
├── data/
│   ├── recipes-unformatted/ # Source files (PDF, images, .txt, .md)
│   └── recipes-formatted/   # Parser output (slug/ingredients.md, steps.md)
└── Makefile                 # docker-cleanup helper
```

## Working with recipes

### Mode 1: Docker (recommended for parsing)

`run_docker.sh` starts Ollama, pulls the model if needed, builds the parser image, and runs one parse job.

```bash
./run_docker.sh <recipe_file_or_url> [recipe_name] [--groceries]
```

| Argument | Description |
|----------|-------------|
| `recipe_file_or_url` | Path to a **PDF**, **image**, or **`.txt`/`.md`** file, or an **http(s) URL** |
| `recipe_name` | Optional slug (e.g. `tuscan-chicken`). Overrides the LLM-generated name. |
| `--groceries` | After a successful parse, import ingredients into Reminders on the Mac |

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

### Mode 2: Batch parse everything

Parse all supported files in `data/recipes-unformatted/` in one shot:

```bash
python3 batch_parse_recipes.py [--dry-run] [--fail-fast] [--groceries]
```

Supported formats: PDF, JPEG, PNG, GIF, WEBP, HEIC, TXT, MD.

### Mode 3: Native Python (no Docker)

Use this if Ollama is already running on your Mac.

```bash
pip install -r requirements.txt
export OLLAMA_HOST=http://localhost:11434

python3 parse_recipe.py /path/to/recipe.pdf --name tuscan-chicken
python3 parse_recipe.py data/recipes-unformatted/hot_dagos_v2.txt --name hot-dagos
python3 parse_recipe.py "https://www.example.com/recipe/print/" --name tuscan-chicken
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
python3 pick_recipe.py
```

If [fzf](https://github.com/junegunn/fzf) is installed, you get a live-filter search — type to narrow, arrow keys to navigate, Enter to select. Without fzf, it falls back to a simple text filter and numbered list.

```bash
python3 pick_recipe.py --dry-run        # preview ingredients without touching Reminders
python3 pick_recipe.py --skip-existing  # skip items already in the list
python3 pick_recipe.py --list "Shopping List"  # use a different Reminders list
```

### Mode 5: Grocery import only

Use this when you already have parsed `ingredients.md` files and only need Reminders updated.

```bash
# By recipe slug
python3 import_groceries.py tuscan-chicken

# By explicit file or recipe directory
python3 import_groceries.py --file data/recipes-formatted/tuscan-chicken/ingredients.md
python3 import_groceries.py --file data/recipes-formatted/tuscan-chicken
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Print ingredient lines without touching Reminders |
| `--skip-existing` | Skip items whose titles already exist in the list (case-insensitive) |
| `--note` | Set the reminder body (default for slug import: `from <slug>`) |
| `--list` | Reminders list name (default: `Groceries`) |
| `--data-dir` | Base `data/` directory for slug lookup |

## Output format

Each parsed recipe gets its own directory:

```
data/recipes-formatted/<recipe-slug>/
├── ingredients.md   # Markdown ingredient lines
└── steps.md         # Markdown instructions
```

The LLM preserves bullets and formatting where possible. `import_groceries.py` reads `ingredients.md` line by line: it skips markdown headers, strips bullet prefixes, and ignores short all-caps section labels (e.g. `SAUCE`, `MEAT PATTIES`). Each remaining line becomes one Reminders title (quantities and prep notes stay on the title).

## Supported inputs

| Format | Parse support |
|--------|----------------|
| PDF (file or URL) | Yes — each page rendered to an image for the vision model |
| Images (JPEG, PNG, HEIC, etc.; file or URL) | Yes — vision model |
| Plain text (`.txt`, `.md`) | Yes — sent as text to the LLM |
| Recipe web pages (`http`/`https`) | Yes — JSON-LD `Recipe` schema when present; otherwise main text via trafilatura + text LLM |

For URLs, use the site's **print** or **print-friendly** link when available (fewer ads and sidebars).

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
python3 pick_recipe.py
```

**Re-import without duplicates:**

```bash
python3 import_groceries.py my-recipe --skip-existing
```

**Parse everything in the unformatted folder:**

```bash
python3 batch_parse_recipes.py
```

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| Model download slow or fails | Ensure Docker has network access; run `docker compose exec ollama ollama pull <model>` manually |
| Parser cannot reach Ollama | In Docker, `OLLAMA_HOST` must be `http://ollama:11434`, not `localhost` |
| Empty or bad extraction | Try a clearer scan or the print URL; use `--name` for a stable folder; try a different `--model` or set `OLLAMA_TEXT_MODEL` for HTML/text |
| URL fetch fails or 403 | Site may block bots; try saving as PDF and parsing the file instead |
| Grocery import finds wrong recipe | Pass the slug explicitly; use `--file` pointing at the right `ingredients.md` |
| `--groceries` cannot resolve slug | Always pass `recipe_name` as the second argument to `run_docker.sh` |
| `pick_recipe.py` shows no recipes | Parse some recipes first — they must exist under `data/recipes-formatted/` |

## Dependencies

**Parser** (`requirements.txt`): PyMuPDF, ollama, pydantic, python-dotenv, requests, trafilatura, beautifulsoup4

**Grocery import / picker**: Python 3.9+ standard library only (`osascript` on macOS); `fzf` optional for `pick_recipe.py`
