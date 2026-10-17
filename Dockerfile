# Build frontend independently: no runtime secrets enter this stage.
FROM node:24.13.0-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.14.0-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH" \
    STORAGE_DIR=/app/storage
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cashier \
    && useradd --uid 10001 --gid cashier --no-create-home cashier
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app/ ./app/
COPY data/ /app/data/
COPY contracts/fixtures/ /app/contracts/fixtures/
COPY --from=frontend /build/frontend/dist/ /app/frontend/dist/
RUN mkdir -p /app/storage && chown -R cashier:cashier /app/storage
USER cashier
EXPOSE 8000
# Exactly one process owns SQLite and the in-process job queue.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
