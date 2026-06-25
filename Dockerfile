FROM python:3.11-slim

WORKDIR /app

ARG USE_ANTHROPIC=false

# System deps for PyMuPDF / image handling; pandoc for document conversion
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ "$USE_ANTHROPIC" = "true" ]; then \
        grep -v "^ollama" requirements.txt > /tmp/req.txt && \
        pip install --no-cache-dir -r /tmp/req.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY processing/ ./processing/
COPY groceries/ ./groceries/

# No ENTRYPOINT: the command passed by `docker compose run` (e.g.
#   python3 processing/parse_recipe.py /input/recipe.pdf) is executed directly.
# To get an interactive shell: docker compose run --rm recipe-manager-app bash