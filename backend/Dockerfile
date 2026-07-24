# ─────────────────────────────────────────────────────────────────────
# Backend image — FastAPI (RBG Annotation Studio API)
#
# Runs the Python API only. The React frontend is built and served
# separately by the `frontend` (nginx) container, which proxies /api and
# /ws to this service. See the repo-root docker-compose.yml.
# ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Fail fast, no .pyc files, no pip cache — keeps the image small and logs clean.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries needed by opencv-python-headless / Pillow at import time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer is cached unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

# Uploaded images and exports live on mounted volumes (see compose), not in the
# image. Point the app's storage at those paths.
ENV STORAGE_DIR=/data/storage \
    EXPORT_DIR=/data/exports
RUN mkdir -p /data/storage /data/exports

EXPOSE 8000

# On startup the app auto-creates any missing tables and seeds the first admin
# (see app/db/database.py). For controlled migrations run `alembic upgrade head`.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
