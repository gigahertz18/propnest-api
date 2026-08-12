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

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .
RUN chown -R appuser:appuser /app

USER appuser

# Default command (overridden in docker-compose.dev.yml for --reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
