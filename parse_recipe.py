import argparse
import json
import logging
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import base64

import fitz  # PyMuPDF
import ollama
import requests
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,image/*,*/*;q=0.8",
}

class Ingredient(BaseModel):
    name: str = Field(description="Base ingredient name, normalized (e.g., 'potato', 'chicken breast', 'olive oil')")
    quantity: str = Field(default="", description="Amount and unit as one string (e.g., '2 lbs', '1/2 cup', '3 cloves', 'to taste'). Empty string if unspecified.")
    prep_note: str = Field(default="", description="Preparation instruction for this ingredient (e.g., 'diced', 'finely chopped', 'room temperature'). Empty string if none.")
    section: str = Field(default="", description="Ingredient group/section header if the recipe groups ingredients (e.g., 'sauce', 'marinade'). Empty string if ungrouped.")
    optional: bool = Field(default=False, description="True if the recipe explicitly marks this ingredient as optional.")


class RecipeStructure(BaseModel):
    recipe_name_slug: str = Field(description="A concise, URL-friendly, all-lowercase name for this recipe (e.g., 'tuscan-chicken'). Max 4 words.")
    ingredients: List[Ingredient] = Field(description="Structured list of ingredients.")
    steps: str = Field(description="The full markdown text for the steps/instructions section")


def is_url(source: str) -> bool:
    try:
        parsed = urlparse(source.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    words = [w for w in slug.split("-") if w][:4]
    return "-".join(words) if words else "unknown-recipe"


def fetch_url(url: str) -> Tuple[bytes, str]:
    """Download a URL; returns body bytes and a MIME type hint."""
    logging.info("Fetching URL: %s", url)
    response = requests.get(
        url,
        headers=FETCH_HEADERS,
        timeout=60,
        allow_redirects=True,
        stream=True,
    )
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Response exceeds {MAX_DOWNLOAD_BYTES} byte limit.")
        chunks.append(chunk)

    body = b"".join(chunks)
    if not body:
        raise ValueError("URL returned an empty response.")

    if not content_type:
        content_type = mimetypes.guess_type(response.url)[0] or ""

    logging.info("Downloaded %d bytes (%s)", len(body), content_type or "unknown type")
    return body, content_type


def get_images_from_bytes(data: bytes, mime_hint: str = "", name_hint: str = "") -> List[bytes]:
    """Convert PDF bytes or raw image bytes into PNG page images for the vision model."""
    images = []
    lower_name = name_hint.lower()
    is_pdf = (
        mime_hint == "application/pdf"
        or lower_name.endswith(".pdf")
        or data[:4] == b"%PDF"
    )

    if is_pdf:
        try:
            logging.info("Converting PDF to images...")
            doc = fitz.open(stream=data, filetype="pdf")
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                images.append(pix.tobytes("png"))
            doc.close()
        except Exception as e:
            logging.error("Error reading PDF: %s", e)
    else:
        images.append(data)

    return images


def get_images_from_file(file_path: Path) -> List[bytes]:
    file_str = str(file_path)
    mime_type, _ = mimetypes.guess_type(file_str)
    with open(file_str, "rb") as f:
        data = f.read()
    return get_images_from_bytes(data, mime_hint=mime_type or "", name_hint=file_str)


def _recipe_objects_from_json_ld(data: Any) -> List[Dict[str, Any]]:
    """Collect schema.org Recipe dicts from JSON-LD payloads."""
    recipes = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            node_type = node.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() == "recipe" for t in types):
                recipes.append(node)
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in node:
                    walk(node[key])

    walk(data)
    return recipes


def extract_json_ld_recipe(html: str) -> Optional[Dict[str, Any]]:
    """Return the first schema.org Recipe object found in JSON-LD script tags."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        recipes = _recipe_objects_from_json_ld(data)
        if recipes:
            return recipes[0]
    return None


def _instruction_lines(instructions: Any) -> List[str]:
    lines = []
    if isinstance(instructions, str):
        return [instructions.strip()] if instructions.strip() else []
    if isinstance(instructions, list):
        for item in instructions:
            if isinstance(item, str):
                if item.strip():
                    lines.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("name") or ""
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
    return lines


def recipe_from_json_ld(recipe: Dict[str, Any]) -> Tuple[str, List[Ingredient], str]:
    """Format a schema.org Recipe dict into slug, structured ingredients, steps markdown."""
    name = recipe.get("name") or recipe.get("headline") or "unknown-recipe"
    slug = slugify(str(name))

    raw_ingredients = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
    if isinstance(raw_ingredients, str):
        raw_lines = [line.strip() for line in raw_ingredients.splitlines() if line.strip()]
    else:
        raw_lines = [str(i).strip() for i in raw_ingredients if str(i).strip()]

    # JSON-LD strings are already human-readable (e.g. "1 cup flour, sifted") — store as-is in name.
    ingredients = [Ingredient(name=line) for line in raw_lines]

    instructions = recipe.get("recipeInstructions") or []
    step_lines = _instruction_lines(instructions)
    steps_md = "\n".join(f"{i}. {line}" for i, line in enumerate(step_lines, 1)) if step_lines else ""

    return slug, ingredients, steps_md


def extract_html_text(html: str, url: str) -> str:
    """Extract main text from an HTML recipe / print page."""
    downloaded = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if downloaded and downloaded.strip():
        return downloaded.strip()

    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        "article",
        "[class*='recipe']",
        "[class*='wprm-recipe']",
        "[id*='recipe']",
        "main",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text("\n", strip=True)
            if len(text) > 200:
                return text

    body = soup.body or soup
    return body.get_text("\n", strip=True)


def load_recipe_source(source: str) -> Dict[str, Any]:
    """
    Load a recipe from a local path or URL.
    Returns dict with keys: images (list), text (optional), preparsed (optional tuple).
    """
    if is_url(source):
        body, content_type = fetch_url(source)
        path_hint = urlparse(source).path

        if content_type.startswith("image/") or path_hint.lower().endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic")
        ):
            return {"images": get_images_from_bytes(body, mime_hint=content_type, name_hint=path_hint)}

        if content_type == "application/pdf" or path_hint.lower().endswith(".pdf"):
            return {"images": get_images_from_bytes(body, mime_hint=content_type, name_hint=path_hint)}

        html = body.decode("utf-8", errors="replace")
        recipe = extract_json_ld_recipe(html)
        if recipe:
            logging.info("Found schema.org Recipe JSON-LD; using structured data.")
            slug, ingredients, steps = recipe_from_json_ld(recipe)
            if ingredients or steps:
                return {"images": [], "text": None, "preparsed": (slug, ingredients, steps)}

        text = extract_html_text(html, source)
        if not text or len(text) < 80:
            raise ValueError("Could not extract enough text from the recipe page.")
        logging.info("Extracted %d characters of text from HTML.", len(text))
        return {"images": [], "text": text}

    input_path = Path(source)
    if not input_path.exists():
        raise FileNotFoundError(f"Input '{source}' does not exist.")

    if input_path.suffix.lower() in (".txt", ".md"):
        text = input_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            raise ValueError(f"File '{source}' is empty.")
        return {"images": [], "text": text}

    return {"images": get_images_from_file(input_path), "text": None}


def _ollama_client():
    ollama_host = os.environ.get("OLLAMA_HOST")
    if not ollama_host:
        raise ValueError(
            "OLLAMA_HOST environment variable not found. Please ensure it is set (e.g., in .env)."
        )
    return ollama.Client(host=ollama_host)


def _use_anthropic() -> bool:
    val = os.environ.get("USE_ANTHROPIC", "").strip().lower()
    return val in ("1", "true", "yes")


def parse_with_llm(
    images: Optional[List[bytes]] = None,
    text: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Tuple[Optional[str], List[Ingredient], str]:
    """Extract recipe fields from images and/or page text.

    Dispatches to the Anthropic API when USE_ANTHROPIC=true, otherwise uses Ollama.
    """
    if not images and not text:
        logging.error("No images or text to process.")
        return None, [], ""

    if _use_anthropic():
        return parse_with_claude(images=images, text=text)

    if images:
        message: Dict[str, Any] = {"role": "user", "content": _IMAGE_PROMPT, "images": images}
        log_label = "document images"
    else:
        message = {"role": "user", "content": _TEXT_PROMPT + (text or "")}
        log_label = "page text"

    try:
        client = _ollama_client()
        text_model = os.environ.get("OLLAMA_TEXT_MODEL")
        vision_model = model_name or os.environ.get("OLLAMA_MODEL", "qwen2.5vl:3b")
        actual_model = vision_model if images else (text_model or vision_model)

        logging.info("Sending %s to Ollama for extraction (%s)...", log_label, actual_model)
        response = client.chat(
            model=actual_model,
            messages=[message],
            format=RecipeStructure.model_json_schema(),
            options={"temperature": 0.1},
        )

        result_json = response.message.content
        parsed_data = json.loads(result_json)
        ingredients = [Ingredient(**i) for i in parsed_data.get("ingredients", [])]

        return (
            parsed_data.get("recipe_name_slug", "unknown-recipe"),
            ingredients,
            parsed_data.get("steps", ""),
        )

    except Exception as e:
        logging.error("Error communicating with Ollama: %s", e)
        return None, [], ""


_INGREDIENT_FORMAT = """
For each ingredient extract:
- name: the base ingredient, normalized (e.g., "potato", "chicken breast", "olive oil")
- quantity: amount and unit as one string (e.g., "2 lbs", "1/2 cup", "3 cloves", "to taste"). Empty string if unspecified.
- prep_note: preparation instruction for this ingredient (e.g., "diced", "finely chopped", "room temperature"). Empty string if none.
- section: group/section header if the recipe clusters ingredients under headings (e.g., "sauce", "marinade"). Empty string if ungrouped.
- optional: true only if the recipe explicitly marks this ingredient as optional.

Do not write "juice of one lemon" — instead name="lemon", quantity="1", prep_note="juiced"."""

_IMAGE_PROMPT = f"""You are an expert recipe parser. I have provided you with images of a recipe document.
Extract EXACTLY three fields:
1. A concise, URL-friendly, all-lowercase slug for this recipe (e.g., "tuscan-chicken"). Max 4 words.
2. A structured list of ingredients.
3. The preparation steps / instructions.
{_INGREDIENT_FORMAT}
Format the steps section preserving the original detail and structure using markdown.
Return the final output exactly as requested by the schema. Do not add conversational text."""

_TEXT_PROMPT = f"""You are an expert recipe parser. I have provided the text of a recipe web page.
Extract EXACTLY three fields:
1. A concise, URL-friendly, all-lowercase slug for this recipe (e.g., "tuscan-chicken"). Max 4 words.
2. A structured list of ingredients.
3. The preparation steps / instructions.
{_INGREDIENT_FORMAT}
Format the steps section preserving the original detail and structure using markdown.
Ignore navigation, ads, comments, and other non-recipe content.
Return the final output exactly as requested by the schema. Do not add conversational text.

Recipe page text:
---
"""

_EXTRACT_RECIPE_TOOL = {
    "name": "extract_recipe",
    "description": "Extract structured recipe data from the provided content.",
    "input_schema": RecipeStructure.model_json_schema(),
}


def parse_with_claude(
    images: Optional[List[bytes]] = None,
    text: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Tuple[Optional[str], List[Ingredient], str]:
    """Extract recipe fields using the Anthropic API with forced tool_use for structured output."""
    try:
        import anthropic
    except ImportError:
        logging.error("anthropic package not installed. Run: pip install anthropic")
        return None, [], ""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logging.error("ANTHROPIC_API_KEY not set.")
        return None, [], ""

    model = model_name or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=api_key)

    if images:
        content: List[Any] = []
        for img_bytes in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(img_bytes).decode("utf-8"),
                },
            })
        content.append({"type": "text", "text": _IMAGE_PROMPT})
        log_label = "document images"
    else:
        content = [{"type": "text", "text": _TEXT_PROMPT + (text or "")}]
        log_label = "page text"

    try:
        logging.info("Sending %s to Claude for extraction (%s)...", log_label, model)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            tools=[_EXTRACT_RECIPE_TOOL],
            tool_choice={"type": "tool", "name": "extract_recipe"},
            messages=[{"role": "user", "content": content}],
        )

        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"),
            None,
        )
        if not tool_use_block:
            logging.error("Claude did not return a tool_use block.")
            return None, [], ""

        parsed = tool_use_block.input
        ingredients = [Ingredient(**i) for i in parsed.get("ingredients", [])]
        return (
            parsed.get("recipe_name_slug", "unknown-recipe"),
            ingredients,
            parsed.get("steps", ""),
        )

    except Exception as e:
        logging.error("Error communicating with Anthropic API: %s", e)
        return None, [], ""


def write_recipe_output(
    data_dir: str,
    final_name: str,
    ingredients: List[Ingredient],
    steps: str,
) -> Tuple[Path, Path]:
    recipe_dir = Path(os.getcwd()) / data_dir / final_name
    recipe_dir.mkdir(parents=True, exist_ok=True)

    ingredients_file = recipe_dir / "ingredients.json"
    steps_file = recipe_dir / "steps.md"

    with open(ingredients_file, "w", encoding="utf-8") as f:
        json.dump([i.model_dump() for i in ingredients], f, indent=2, ensure_ascii=False)

    with open(steps_file, "w", encoding="utf-8") as f:
        f.write("# Steps\n\n")
        f.write(steps if steps else "No steps/instructions found.\n")

    return ingredients_file, steps_file


def main():
    parser = argparse.ArgumentParser(
        description="Parse a recipe document or URL into ingredients and steps using a local or cloud LLM."
    )
    parser.add_argument(
        "input_source",
        help="Path to a recipe file (PDF, image) or http(s) URL (e.g. a print-friendly recipe page)",
    )
    parser.add_argument(
        "--name",
        required=False,
        help="Optional name of the recipe. If omitted, the LLM or page metadata will suggest one.",
    )
    parser.add_argument(
        "--data-dir",
        default="data/recipes-formatted",
        help="Base directory for output (default: data/recipes-formatted)",
    )

    default_model = os.environ.get("OLLAMA_MODEL", "qwen2.5vl:3b")
    parser.add_argument(
        "--model",
        default=default_model,
        help=f"The Ollama model to use for vision extraction (default: {default_model})",
    )
    parser.add_argument(
        "--use-anthropic",
        action="store_true",
        default=_use_anthropic(),
        help="Use the Anthropic API instead of local Ollama (requires ANTHROPIC_API_KEY; also set via USE_ANTHROPIC=true).",
    )
    parser.add_argument(
        "--import-groceries",
        action="store_true",
        help="After parsing, import ingredients into macOS Reminders (Groceries list). macOS only.",
    )

    args = parser.parse_args()

    if args.use_anthropic:
        os.environ["USE_ANTHROPIC"] = "true"

    try:
        loaded = load_recipe_source(args.input_source)
    except (FileNotFoundError, ValueError, requests.RequestException) as e:
        logging.error("%s", e)
        return

    logging.info("Parsing recipe: %s", args.input_source)

    if loaded.get("preparsed"):
        inferred_name, ingredients, steps = loaded["preparsed"]
    elif loaded.get("text"):
        inferred_name, ingredients, steps = parse_with_llm(text=loaded["text"], model_name=args.model)
    else:
        images = loaded.get("images") or []
        if not images:
            logging.error("Failed to load document imagery. Aborting.")
            return
        inferred_name, ingredients, steps = parse_with_llm(images=images, model_name=args.model)

    env_name = os.environ.get("RECIPE_NAME")
    final_name = args.name or env_name or inferred_name
    if not final_name:
        final_name = "unnamed-recipe"

    ingredients_file, steps_file = write_recipe_output(
        args.data_dir, final_name, ingredients, steps
    )

    logging.info("Success! Wrote structured recipe files to:")
    logging.info("  - %s", ingredients_file)
    logging.info("  - %s", steps_file)

    if args.import_groceries:
        if sys.platform != "darwin":
            logging.warning("--import-groceries is only supported on macOS; skipping.")
        else:
            from import_groceries import add_to_reminders, parse_ingredients_json

            items = parse_ingredients_json(ingredients_file, recipe_name=final_name)
            add_to_reminders(items)


if __name__ == "__main__":
    main()
