# ─── Python ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements/base.txt requirements/base.txt
COPY requirements/prod.txt requirements/prod.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements/prod.txt

# Copy project source
COPY . .

# Collect static files
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
RUN python manage.py collectstatic --noinput || true

# ─── Development image ───────────────────────────────────────────────────────
FROM base AS dev
COPY requirements/dev.txt requirements/dev.txt
RUN pip install --no-cache-dir -r requirements/dev.txt

# ─── Production image ────────────────────────────────────────────────────────
FROM base AS prod

# Run as non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8000

# Default: run with Gunicorn (HTTP). Override CMD for Daphne (ASGI/WS).
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
