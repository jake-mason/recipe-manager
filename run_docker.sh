#!/bin/bash

# Wrapper to run the recipe parser using Docker Compose (which includes Ollama)

IMPORT_GROCERIES=false
SYNC_ICLOUD=false
POSITIONAL=()

for arg in "$@"; do
    case "$arg" in
        --groceries)
            IMPORT_GROCERIES=true
            ;;
        --sync)
            SYNC_ICLOUD=true
            ;;
        *)
            POSITIONAL+=("$arg")
            ;;
    esac
done

if [ "${#POSITIONAL[@]}" -lt 1 ] || [ "${#POSITIONAL[@]}" -gt 2 ]; then
    echo "Usage: ./run_docker.sh <recipe_file_or_url> [recipe_name] [--groceries] [--sync]"
    echo "Example: ./run_docker.sh /path/to/shared/recipes/lasagna.pdf lasagna"
    echo "         ./run_docker.sh /path/to/shared/recipes/pizza.jpg"
    echo "         ./run_docker.sh https://example.com/recipe/print/ lasagna --groceries"
    exit 1
fi

INPUT_SOURCE="${POSITIONAL[0]}"
RECIPE_NAME=${POSITIONAL[1]:-""}

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$INPUT_SOURCE" =~ ^https?:// ]]; then
    PARSER_COMMAND=("$INPUT_SOURCE")
    # Compose still expects a volume mount; URL fetching happens inside the container.
    export INPUT_DIR="${PROJECT_DIR}/data"
    export FILENAME="."
else
    INPUT_PATH=$(realpath "$INPUT_SOURCE")
    if [ ! -f "$INPUT_PATH" ]; then
        echo "Error: File '$INPUT_PATH' does not exist."
        exit 1
    fi
    export INPUT_DIR=$(dirname "$INPUT_PATH")
    export FILENAME=$(basename "$INPUT_PATH")
    PARSER_COMMAND=("/input/${FILENAME}")
fi

export OUTPUT_DIR="${PROJECT_DIR}/data"
export RECIPE_NAME

# Source environment variables
if [ -f "${PROJECT_DIR}/.env" ]; then
    set -a
    source "${PROJECT_DIR}/.env"
    set +a
fi

if [ "${USE_ANTHROPIC:-false}" != "true" ]; then
    echo "Starting environment and pulling model if needed (this may take a while the first time)..."

    # Ensure Ollama is running in the background
    docker compose --profile ollama up -d ollama

    # Print the installed Ollama version
    echo "Ollama version running in container:"
    docker compose exec ollama ollama --version

    # Wait for Ollama to be ready
    echo "Waiting for Ollama to start..."
    sleep 5

    # Pull the specified model (this takes time initially, but is fast if already downloaded)
    # Defaulting to qwen2.5vl:3b if OLLAMA_MODEL is not set in .env
    OLLAMA_MODEL=${OLLAMA_MODEL:-"qwen2.5vl:3b"}
    echo "Ensuring ${OLLAMA_MODEL} is downloaded..."
    docker compose exec ollama ollama pull ${OLLAMA_MODEL}
fi

# Run the parser app and capture its output to the terminal
# Using --build --no-cache to ensure it is always built freshly
echo "Building and running recipe parser..."
# #region agent log
DEBUG_LOG="${PROJECT_DIR}/.cursor/debug-3bb3db.log"
mkdir -p "$(dirname "$DEBUG_LOG")"
printf '{"sessionId":"3bb3db","runId":"pre-fix","hypothesisId":"H1","location":"run_docker.sh:docker-run","message":"docker compose command","data":{"parser_command":"%s","recipe_name":"%s","input_dir":"%s","filename":"%s"},"timestamp":%s}\n' \
    "$(printf '%s' "${PARSER_COMMAND[*]}" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$RECIPE_NAME" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$INPUT_DIR" | sed 's/"/\\"/g')" \
    "$(printf '%s' "$FILENAME" | sed 's/"/\\"/g')" \
    "$(($(date +%s) * 1000))" >> "$DEBUG_LOG"
# #endregion
docker compose run --rm --build -e "RECIPE_NAME=${RECIPE_NAME}" recipe-manager-app "${PARSER_COMMAND[@]}"
PARSE_EXIT=$?
# #region agent log
printf '{"sessionId":"3bb3db","runId":"pre-fix","hypothesisId":"H1","location":"run_docker.sh:docker-exit","message":"docker compose exit","data":{"exit_code":%s},"timestamp":%s}\n' \
    "$PARSE_EXIT" "$(($(date +%s) * 1000))" >> "$DEBUG_LOG"
# #endregion

if [ "$PARSE_EXIT" -ne 0 ]; then
    echo "Recipe parsing failed (exit $PARSE_EXIT)."
    exit "$PARSE_EXIT"
fi

# Resolve the recipe slug once for any post-parse host steps (groceries / sync).
RESOLVED_SLUG="$RECIPE_NAME"
if { [ "$IMPORT_GROCERIES" = true ] || [ "$SYNC_ICLOUD" = true ]; } && [ -z "$RESOLVED_SLUG" ]; then
    LATEST_DIR=$(ls -td "${PROJECT_DIR}/data/recipes-formatted"/*/ 2>/dev/null | head -1)
    if [ -n "$LATEST_DIR" ]; then
        RESOLVED_SLUG=$(basename "$LATEST_DIR")
    fi
fi

if [ "$IMPORT_GROCERIES" = true ]; then
    echo "Importing ingredients to Reminders..."
    if [ -z "$RESOLVED_SLUG" ]; then
        echo "Error: could not determine recipe slug for grocery import. Pass a recipe name or run import manually."
        exit 1
    fi
    python3 "${PROJECT_DIR}/groceries/import_groceries.py" "$RESOLVED_SLUG" --data-dir "${PROJECT_DIR}/data"
    GROCERY_EXIT=$?
    if [ "$GROCERY_EXIT" -ne 0 ]; then
        exit "$GROCERY_EXIT"
    fi
fi

if [ "$SYNC_ICLOUD" = true ]; then
    echo "Syncing recipe to iCloud folder..."
    if [ -z "$RESOLVED_SLUG" ]; then
        echo "Error: could not determine recipe slug for iCloud sync. Pass a recipe name or run sync manually."
        exit 1
    fi
    python3 "${PROJECT_DIR}/processing/sync_to_icloud.py" "$RESOLVED_SLUG" --data-dir "${PROJECT_DIR}/data"
    SYNC_EXIT=$?
    if [ "$SYNC_EXIT" -ne 0 ]; then
        exit "$SYNC_EXIT"
    fi
fi

echo "Done! The containers will remain running in the background for faster subsequent runs."
echo "To stop them, run: docker compose down"
