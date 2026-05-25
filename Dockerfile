FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF / image handling
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parse_recipe.py .

ENTRYPOINT ["bash"]