# Backend only. ML models stay on the host, outside this build context.
FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.14.0-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
WORKDIR /app
COPY backend/app/ backend/app/
COPY contracts/fixtures/ contracts/fixtures/
COPY ml2/patches/backend-ml-timeouts.patch /opt/backend-ml-timeouts.patch
# Windows may check out Python sources as CRLF; normalize only the image copy.
RUN python -c "from pathlib import Path; [p.write_text(p.read_text(encoding='utf-8'), encoding='utf-8', newline='\n') for p in Path('backend/app').rglob('*.py')]" \
    && if git apply --check /opt/backend-ml-timeouts.patch >/dev/null 2>&1; then \
         git apply /opt/backend-ml-timeouts.patch; \
       elif git apply --reverse --check /opt/backend-ml-timeouts.patch >/dev/null 2>&1; then \
         echo "timeouts already applied"; \
       else \
         echo "ERROR: timeout patch neither applies nor matches an already-applied state" >&2; exit 1; \
       fi
WORKDIR /app/backend
RUN python -c "from app import pipeline as p; assert (p.ML1_READ_TIMEOUT_SECONDS,p.ML_REQUEST_TIMEOUT_SECONDS,p.ML2_READ_TIMEOUT_SECONDS,p.ML2_REQUEST_TIMEOUT_SECONDS)==(180,190,90,100)"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
