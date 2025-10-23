FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates git curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Устанавливаем Chromium и зависимости Playwright
RUN python -m playwright install --with-deps chromium

COPY scraper.py .

# По умолчанию headless
ENV HEADLESS=1
CMD ["python", "scraper.py"]
