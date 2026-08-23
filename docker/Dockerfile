# ─── Builder: compiles anything needing gcc/libpq-dev, isolated from the runtime image ───
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime: no build tooling, no root user ───
FROM python:3.12-slim

# WeasyPrint (PDF receipt rendering) loads Pango/Cairo/GDK-Pixbuf at runtime via cffi —
# these aren't Python packages, so pip install alone won't provide them.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .
RUN chown -R appuser:appuser /app
RUN chmod +x docker/entrypoint.sh

USER appuser

ENTRYPOINT ["sh", "docker/entrypoint.sh"]
# Default command - docker-compose.yml's `worker` service overrides this with arq instead
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
