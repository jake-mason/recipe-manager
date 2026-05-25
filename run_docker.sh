#!/bin/bash

# Wrapper to run the recipe parser using Docker Compose (which includes Ollama)

IMPORT_GROCERIES=false
POSITIONAL=()

for arg in "$@"; do
    case "$arg" in
        --groceries)
            IMPORT_GROCERIES=true
            ;;
        *)
            POSITIONAL+=("$arg")
            ;;
    esac
done

if [ "${#POSITIONAL[@]}" -lt 1 ] || [ "${#POSITIONAL[@]}" -gt 2 ]; then
    echo "Usage: ./run_docker.sh <recipe_file_or_url> [recipe_name] [--groceries]"
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

echo "Starting environment and pulling model if needed (this may take a while the first time)..."

# Ensure Ollama is running in the background
docker compose up -d ollama

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

# Run the parser app and capture its output to the terminal
# Using --build --no-cache to ensure it is always built freshly
echo "Building and running recipe parser..."
docker compose run --rm --build recipe-parser-app "${PARSER_COMMAND[@]}"
PARSE_EXIT=$?

if [ "$PARSE_EXIT" -ne 0 ]; then
    echo "Recipe parsing failed (exit $PARSE_EXIT)."
    exit "$PARSE_EXIT"
fi

if [ "$IMPORT_GROCERIES" = true ]; then
    echo "Importing ingredients to Reminders..."
    IMPORT_SLUG="$RECIPE_NAME"
    if [ -z "$IMPORT_SLUG" ]; then
        LATEST_DIR=$(ls -td "${PROJECT_DIR}/data/recipes-formatted"/*/ 2>/dev/null | head -1)
        if [ -n "$LATEST_DIR" ]; then
            IMPORT_SLUG=$(basename "$LATEST_DIR")
        fi
    fi
    if [ -z "$IMPORT_SLUG" ]; then
        echo "Error: could not determine recipe slug for grocery import. Pass a recipe name or run import manually."
        exit 1
    fi
    python3 "${PROJECT_DIR}/import_groceries.py" "$IMPORT_SLUG" --data-dir "${PROJECT_DIR}/data"
    GROCERY_EXIT=$?
    if [ "$GROCERY_EXIT" -ne 0 ]; then
        exit "$GROCERY_EXIT"
    fi
fi

echo "Done! The containers will remain running in the background for faster subsequent runs."
echo "To stop them, run: docker compose down"
