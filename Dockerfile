FROM python:3.11-slim

WORKDIR /app

# Enable the non-free repository so apt can find 'unrar'
RUN sed -i 's/Components: main/Components: main non-free/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/ main/ main non-free/g' /etc/apt/sources.list 2>/dev/null || true

# Install system dependencies required for cryptography, zip, and rar operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    unzip \
    unrar \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure temp directory exists for file processing
RUN mkdir -p temp

CMD ["python", "bot.py"]
