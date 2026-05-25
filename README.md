# Recipe Manager

Turn recipe photos, PDFs, and **recipe URLs** (including print-friendly pages) into structured markdown (ingredients + steps) using a local LLM, then optionally push ingredients into the **Groceries** list in macOS Reminders (which syncs to iOS via iCloud).

## What it does

1. **Parse** — Send an image, PDF, or **http(s) URL** to [Ollama](https://ollama.com). Images and PDFs use a vision model; web pages use structured JSON-LD when available, otherwise extracted page text.
2. **Import groceries** (macOS only) — Read a parsed `ingredients.md` and create one Reminders item per ingredient line in your **Groceries** list.

Parsing runs in Docker (Linux). Reminders import runs on the **Mac host** only (AppleScript cannot run inside the container).

## Prerequisites

- **Docker** and **Docker Compose**
- Enough disk/RAM for Ollama and a vision model (default: `qwen2.5vl:3b`)
- **macOS** (for grocery import): Reminders app with a list named exactly **Groceries**, signed into the same iCloud account as your iPhone

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
| `OLLAMA_MODEL` | Vision model tag for PDF/image extraction (and fallback for HTML text). |
| `OLLAMA_TEXT_MODEL` | Optional text-only model for HTML pages (e.g. `qwen2.5:3b`). Defaults to `OLLAMA_MODEL` if unset. |

When using `run_docker.sh`, you can also set `RECIPE_NAME` via the optional second argument (exported automatically by the script).

## Project layout

```
recipe-manager/
├── parse_recipe.py          # Core parser (PDF/image → markdown)
├── import_groceries.py      # macOS Reminders import (host only)
├── run_docker.sh            # Recommended entry point (Docker + optional groceries)
├── docker-compose.yml       # Ollama + one-shot parser service
├── Dockerfile
├── data/
│   ├── recipes-unformatted/ # Example sources (PDF, images; .md/.txt not parsed yet)
│   └── recipes-formatted/   # Default parser output (slug/ingredients.md, steps.md)
│       └── tuscan-chicken/  # Example parsed recipe
└── Makefile                 # docker-cleanup helper
```

## Working with recipes

There are three ways to use the project, depending on whether you want Docker, native parsing, or grocery import alone.

### Mode 1: Docker (recommended)

`run_docker.sh` starts Ollama, pulls the model if needed, builds the parser image, and runs one parse job.

```bash
./run_docker.sh <recipe_file_or_url> [recipe_name] [--groceries]
```

| Argument | Description |
|----------|-------------|
| `recipe_file_or_url` | Path to a **PDF** or **image**, or an **http(s) URL** (print/recipe page) |
| `recipe_name` | Optional slug (e.g. `tuscan-chicken`). Overrides the LLM-generated name. |
| `--groceries` | After a successful parse, import ingredients into Reminders on the Mac |

**Examples:**

```bash
./run_docker.sh ~/Downloads/lasagna.pdf lasagna
./run_docker.sh ~/Pictures/recipe-card.jpg
./run_docker.sh "https://www.example.com/recipe/print/" honey-garlic-chicken
./run_docker.sh data/recipes-unformatted/Honey_Garlic_Chicken_Amplified.pdf honey-garlic-chicken --groceries
```

**Stop background services:**

```bash
docker compose down
```

**Full cleanup** (containers, volumes, built image):

```bash
make docker-cleanup
```

#### What Docker runs

- **`ollama`** — Long-lived service on port `11434`, model data in a named volume.
- **`recipe-parser-app`** — One-shot container: mounts your input file at `/input/<filename>` and writes output to `data/` (mapped to `/app/data` in the container). Default output path inside the parser is `data/recipes-formatted/<slug>/`.

### Mode 2: Native Python (no Docker)

Use this if Ollama is already running on your Mac and you want to parse without containers.

```bash
pip install -r requirements.txt

# Point at local Ollama (override .env if it says http://ollama:11434)
export OLLAMA_HOST=http://localhost:11434

python3 parse_recipe.py /path/to/recipe.pdf --name tuscan-chicken
python3 parse_recipe.py "https://www.example.com/recipe/print/" --name tuscan-chicken
```

**Options:**

| Flag | Description |
|------|-------------|
| `--name` | Recipe slug for the output folder |
| `--data-dir` | Base output directory (default: `data/recipes-formatted`) |
| `--model` | Ollama model tag (default: `OLLAMA_MODEL` or `qwen2.5vl:3b`) |
| `--import-groceries` | After writing files, import into Reminders (macOS only) |

**Example — parse and import in one command:**

```bash
python3 parse_recipe.py recipe.pdf --name tuscan-chicken --import-groceries
```

On Linux or inside Docker, `--import-groceries` logs a warning and is skipped.

### Mode 3: Grocery import only

Use this when you already have parsed `ingredients.md` files and only need Reminders updated.

```bash
# By recipe slug (looks under data/recipes-formatted/<slug>/ and data/<slug>/)
python3 import_groceries.py tuscan-chicken

# By explicit file or recipe directory
python3 import_groceries.py --file data/tuscan-chicken/ingredients.md
python3 import_groceries.py --file data/tuscan-chicken
```

**Options:**

| Flag | Description |
|------|-------------|
| `--dry-run` | Print ingredient lines without touching Reminders |
| `--skip-existing` | Skip items whose titles already exist in the list (case-insensitive) |
| `--note` | Set the reminder body (default for slug import: `from <slug>`) |
| `--list` | Reminders list name (default: `Groceries`) |
| `--data-dir` | Base `data/` directory for slug lookup |

**Examples:**

```bash
python3 import_groceries.py tuscan-chicken --dry-run
python3 import_groceries.py tuscan-chicken --skip-existing
python3 import_groceries.py --file data/recipes-formatted/tuscan-chicken/ingredients.md --note "meal prep"
```

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
| PDF (file or URL) | Yes (each page rendered to an image for the vision model) |
| Images (JPEG, PNG, etc.; file or URL) | Yes |
| Recipe web pages (`http`/`https`) | Yes — JSON-LD `Recipe` schema when present; otherwise main text via trafilatura + text LLM |
| Plain `.md` / `.txt` in `data/recipes-unformatted/` | **No** — not wired into the parser yet |

For URLs, use the site’s **print** or **print-friendly** link when available (fewer ads and sidebars). Many sites embed [schema.org](https://schema.org/Recipe) JSON-LD, which is parsed directly without calling the LLM.

## macOS Reminders setup

1. Open **Reminders** and create or confirm a list named **Groceries** (must match exactly unless you pass `--list`).
2. Sign in to iCloud on Mac and iPhone so lists sync.
3. On first import, macOS may prompt for **Automation** permission — allow your terminal app (Terminal, iTerm, or Cursor) to control **Reminders**.

If import fails with `Not authorized to send Apple events to Reminders`, enable access under **System Settings → Privacy & Security → Automation**.

Items created on the Mac should appear on iPhone in **Reminders → Groceries** after iCloud sync (usually seconds).

## Typical workflows

**New recipe from a photo/PDF:**

```bash
./run_docker.sh ~/Downloads/recipe-scan.pdf my-recipe-slug
# Review data/recipes-formatted/my-recipe-slug/
python3 import_groceries.py my-recipe-slug
```

**One-shot parse + groceries:**

```bash
./run_docker.sh ~/Downloads/recipe.pdf my-recipe-slug --groceries
```

**Re-import without duplicates:**

```bash
python3 import_groceries.py my-recipe-slug --skip-existing
```

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| Model download slow or fails | Ensure Docker has network access; run `docker compose exec ollama ollama pull <model>` manually |
| Parser cannot reach Ollama | In Docker, `OLLAMA_HOST` must be `http://ollama:11434`, not `localhost` |
| Empty or bad extraction | Try a clearer scan or the print URL; use `--name` for a stable folder; try a different `--model` or set `OLLAMA_TEXT_MODEL` for HTML |
| URL fetch fails or 403 | Site may block bots; try saving as PDF and parsing the file instead |
| Grocery import finds wrong recipe | Pass the slug explicitly; use `--file` pointing at the right `ingredients.md` |
| `--groceries` cannot resolve slug | Always pass `recipe_name` as the second argument to `run_docker.sh` |

## Dependencies

**Parser** (`requirements.txt`): PyMuPDF, ollama, pydantic, python-dotenv, requests, trafilatura, beautifulsoup4  

**Grocery import**: Python 3.9+ standard library only (`osascript` on macOS)
