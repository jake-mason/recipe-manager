"""Local on-disk cache for LLM parse results, keyed by a hash of the input.

The same recipe input (PDF/image bytes or page text) parsed with the same
backend/model/prompt always yields the same structured result, so we persist
results to disk and skip the (often paid) LLM call on a cache hit.

The cache lives under ``data/.parse-cache/`` by default so it persists across
Docker runs (``./data`` is volume-mounted) and on the host. Override the
location with ``RECIPE_CACHE_DIR`` or disable entirely with
``RECIPE_CACHE_DISABLED=true``.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

# Bump when the cached payload shape changes in a backward-incompatible way.
CACHE_VERSION = 1

_REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def cache_enabled() -> bool:
    return not _truthy(os.environ.get("RECIPE_CACHE_DISABLED"))


def cache_dir() -> Path:
    override = os.environ.get("RECIPE_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return _REPO_ROOT / "data" / ".parse-cache"


def compute_key(
    images: Optional[List[bytes]],
    text: Optional[str],
    backend: str,
    model_id: str,
    prompt: str,
    schema: str,
) -> str:
    """Derive a stable cache key from the input content and the parsing context.

    The key folds in the backend, model, prompt, and output schema so that
    changing any of them produces a fresh key instead of returning a stale
    result generated under different conditions.
    """
    hasher = hashlib.sha256()

    def update(label: str, blob: bytes) -> None:
        # Length-prefix each field so concatenation is unambiguous.
        hasher.update(label.encode("utf-8"))
        hasher.update(str(len(blob)).encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(blob)

    update("version", str(CACHE_VERSION).encode("utf-8"))
    update("backend", backend.encode("utf-8"))
    update("model", model_id.encode("utf-8"))
    update("prompt", prompt.encode("utf-8"))
    update("schema", schema.encode("utf-8"))

    if images:
        update("kind", b"images")
        update("image_count", str(len(images)).encode("utf-8"))
        for img in images:
            update("image", img)
    else:
        update("kind", b"text")
        update("text", (text or "").encode("utf-8"))

    return hasher.hexdigest()


def _path_for(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def load(key: str) -> Optional[Tuple[str, List[dict], str]]:
    """Return (slug, ingredient_dicts, steps) for a cache hit, else None."""
    if not cache_enabled():
        logger.debug("Cache disabled (RECIPE_CACHE_DISABLED); not checking for key %s.", key[:12])
        return None
    path = _path_for(key)
    if not path.exists():
        logger.info(
            "Cache miss (%s): no prior parse for this input; an LLM call is needed.",
            key[:12],
        )
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        result = payload["slug"], payload["ingredients"], payload["steps"]
        logger.debug("Cache hit (%s): loaded %s from %s.", key[:12], payload["slug"], path)
        return result
    except (OSError, ValueError, KeyError) as e:
        logger.warning("Ignoring unreadable cache entry %s: %s", path.name, e)
        return None


def store(key: str, slug: str, ingredients: List[dict], steps: str) -> None:
    """Persist a parse result. Failures are logged but never raised."""
    if not cache_enabled():
        logger.debug("Cache disabled (RECIPE_CACHE_DISABLED); not storing key %s.", key[:12])
        return
    path = _path_for(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"slug": slug, "ingredients": ingredients, "steps": steps},
                f,
                ensure_ascii=False,
            )
        tmp.replace(path)
        logger.info(
            "Cached parse result (%s) for slug=%s; future identical inputs will skip the LLM.",
            key[:12], slug,
        )
    except OSError as e:
        logger.warning("Could not write cache entry %s: %s", path.name, e)
