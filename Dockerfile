FROM python:3.11-slim

WORKDIR /app

ARG USE_ANTHROPIC=false

# System deps for PyMuPDF / image handling
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ "$USE_ANTHROPIC" = "true" ]; then \
        grep -v "^ollama" requirements.txt > /tmp/req.txt && \
        pip install --no-cache-dir -r /tmp/req.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY parse_recipe.py .

ENTRYPOINT ["python", "parse_recipe.py"]