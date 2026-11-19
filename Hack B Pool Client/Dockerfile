# Local development image for the Rackroom client (Vite dev server with HMR).
# Used by compose.yaml at the repo root.
#
#   docker compose up --watch client

FROM node:24-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 so the port is reachable from outside the container.
# API_PROXY_TARGET (see vite.config.js) points the /api proxy at the api service.
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
