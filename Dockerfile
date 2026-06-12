FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's/Components: main/Components: main non-free/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/ main/ main non-free/g' /etc/apt/sources.list 2>/dev/null || \
    true

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    unzip \
    unrar \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p temp

CMD ["python", "bot.py"]
