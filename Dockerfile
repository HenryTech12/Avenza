# Stage 1: build the frontend app (frontend/), if the repo has one.
# Same origin as the API: an empty VITE_API_BASE_URL means "this site".
# Debian-based, not Alpine: TypeScript 7 and Vite 8 (rolldown) ship native
# binaries, and the lockfile only has the glibc build of TypeScript's.
FROM node:22-slim AS frontend
WORKDIR /src
COPY . .
ARG VITE_BACKEND_MODE=live
ARG VITE_API_BASE_URL=
ENV VITE_BACKEND_MODE=$VITE_BACKEND_MODE VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN if [ -f frontend/package.json ]; then \
        cd frontend \
        && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
        && npm run build; \
    else \
        echo "no frontend/ in this commit: the legacy web/ PWA will be served"; \
        mkdir -p frontend/dist; \
    fi

# Stage 2: the backend.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools are only needed if a wheel is unavailable for the platform.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY avenza ./avenza
COPY avenza_ai ./avenza_ai
COPY data ./data
COPY web ./web
COPY --from=frontend /src/frontend/dist ./frontend/dist
COPY scripts ./scripts
COPY run.py ./

# /data holds the SQLite database on the Forge cluster (a PersistentVolume).
RUN useradd --create-home --uid 10001 avenza \
    && mkdir -p /data /app/reports \
    && chown -R avenza:avenza /app /data
USER avenza

# Forge sandbox: listen on 0.0.0.0, plain HTTP (TLS ends at Cloudflare and the
# gateway), fixed port 8080 behind the "app" Service on port 80.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/healthz', timeout=4).read()"

# create_app reads configuration from the environment. Proxy headers are only
# trusted from 127.0.0.1 (uvicorn's default), so a client cannot pretend to be
# local to reach admin routes.
CMD ["sh", "-c", "exec uvicorn avenza.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080} --ws-ping-interval 20 --ws-ping-timeout 20"]
