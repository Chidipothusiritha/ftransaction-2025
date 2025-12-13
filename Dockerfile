FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (postgres client is optional; keep if you use psql inside container)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# If you truly need runtime-created dirs, keep this. Otherwise remove.
RUN mkdir -p /app/static/css

# Non-root user (recommended)
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Render/Railway provide PORT; default to 5001 locally
EXPOSE 5001

# IMPORTANT: bind to 0.0.0.0 and use PORT
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-5001} sql_console:app"]
