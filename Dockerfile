# ==========================================
# Stage 1: Build Frontend (Next.js)
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ==========================================
# Stage 2: Production Runner
# Ubuntu 22.04 — Wine + MT5 terminal + Python 3.11 + Node 20
# ==========================================
FROM ubuntu:22.04 AS runner

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEPREFIX=/root/.mt5
ENV WINEARCH=win64
ENV NODE_ENV=production
ENV PYTHONUNBUFFERED=1
ENV NEXT_TELEMETRY_DISABLED=1

# 1. Basic utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates wget gnupg2 software-properties-common procps unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. Wine architecture and repositories
RUN dpkg --add-architecture i386 && \
    mkdir -pm755 /etc/apt/keyrings && \
    wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key && \
    wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources

# 3. Wine and Display (Xvfb)
RUN apt-get update && \
    apt-get install -y --install-recommends \
        winehq-stable xvfb libgl1-mesa-dri && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 4. Python 3.11
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 5. Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Default python3 → python3.11
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Download and silently install MT5 terminal via Wine + virtual display
# Download MT5 terminal installer (will be installed at runtime in entrypoint.sh to bypass build-time emulation issues)
RUN wget https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O /tmp/mt5setup.exe

# ── Backend ──────────────────────────────────────────────────
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY backend/ ./

# ── Frontend ─────────────────────────────────────────────────
WORKDIR /app/frontend

COPY --from=frontend-builder /app/frontend/.next/standalone ./
COPY --from=frontend-builder /app/frontend/.next/static ./.next/static
COPY --from=frontend-builder /app/frontend/public ./public

# ── MT5 config template ───────────────────────────────────────
WORKDIR /app
COPY mt5/ ./mt5/
RUN chmod +x ./mt5/entrypoint.sh

# ── Entrypoint ────────────────────────────────────────────────
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 3000 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
