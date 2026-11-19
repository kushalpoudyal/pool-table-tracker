# Rackroom in one image for deployment: the built React client and the
# FastAPI server that serves it. (compose.yaml and the Dockerfiles inside the
# two app folders are for local development.)
#
#   docker build -t rackroom .
#   docker run --rm -p 8000:8000 -v rackroom-data:/data rackroom
#
# The server listens on $PORT, 8000 by default. The ECS service's load
# balancer expects port 80, so the deploy builds with --build-arg PORT=80.
# The folder names contain spaces, hence the JSON form of COPY.

# ---- Stage 1: build the React client -------------------------------------
FROM node:24-bookworm-slim AS client
WORKDIR /client
COPY ["Hack B Pool Client/package.json", "Hack B Pool Client/package-lock.json", "./"]
RUN npm ci
COPY ["Hack B Pool Client/", "./"]
RUN npm run build

# ---- Stage 2: the server --------------------------------------------------
FROM python:3.12-slim-bookworm AS server

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# main.py looks for the client build at "../Hack B Pool Client/dist", so the
# image keeps the repo's folder layout under /app.
WORKDIR /app/Hack B Pool API
COPY ["Hack B Pool API/requirements.txt", "./"]
RUN pip install -r requirements.txt

COPY ["Hack B Pool API/", "./"]
COPY --from=client ["/client/dist", "/app/Hack B Pool Client/dist"]

# Run unprivileged. /data holds the SQLite database; mount a volume there to
# keep it across restarts.
# The ECS load balancer needs port 80, which a non-root user may not bind on
# Fargate. Granting Python only CAP_NET_BIND_SERVICE allows it without root.
RUN useradd --uid 1000 --user-group --no-create-home rackroom \
    && mkdir /data \
    && chown rackroom:rackroom /data \
    && apt-get update \
    && apt-get install -y --no-install-recommends libcap2-bin \
    && setcap cap_net_bind_service=+ep "$(readlink -f /usr/local/bin/python3)" \
    && apt-get purge -y libcap2-bin \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
USER 1000:1000

ARG PORT=8000
ENV PORT=${PORT} \
    POOL_DB=/data/pool.sqlite3

EXPOSE ${PORT}

# One worker, always: game sessions live in this process's memory, so a
# second worker would not know the sessions of the first.
# --proxy-headers / --forwarded-allow-ips: trust X-Forwarded-* from the load
# balancer in front, so the app knows it is being served over HTTPS.
# --timeout-graceful-shutdown: a deploy must not wait on open phone sockets.
# The shell form expands $PORT; exec keeps uvicorn as PID 1 for clean stops.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --proxy-headers --forwarded-allow-ips '*' --timeout-graceful-shutdown 10"]
