# Local development image for the Rackroom API (FastAPI + uvicorn --reload).
# Used by compose.yaml at the repo root.
#
#   docker compose up --watch api

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dev requirements, so the test suite runs in the container too:
#   docker compose exec api python -m unittest -v
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

# Run unprivileged. /data holds the SQLite database on a named volume, which
# takes this ownership when first created.
RUN useradd --uid 1000 --user-group --no-create-home rackroom \
    && mkdir /data \
    && chown -R rackroom:rackroom /data /app
USER 1000:1000

ENV POOL_DB=/data/pool.sqlite3

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
