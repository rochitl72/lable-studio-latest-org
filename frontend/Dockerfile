# ─────────────────────────────────────────────────────────────────────
# Frontend image — two stages
#   1) build : compile the React/Vite app to static files
#   2) serve : hand those files to nginx, which also reverse-proxies the
#              API (/api) and the collaboration WebSocket (/ws) to the
#              backend container, so the browser only ever talks to one origin.
# ─────────────────────────────────────────────────────────────────────

# ─── Stage 1: build ──────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app

# Install dependencies from the lockfile first (cached unless deps change).
COPY package.json package-lock.json ./
RUN npm ci

# Build the production bundle into /app/dist.
COPY . .
RUN npm run build

# ─── Stage 2: serve ──────────────────────────────────────────────────
FROM nginx:1.27-alpine

# SPA + reverse-proxy config (routes /api and /ws to the backend service).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Only the compiled assets ship in the final image — no Node, no source.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
