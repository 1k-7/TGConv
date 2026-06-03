FROM python:3.11-slim

WORKDIR /app

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
