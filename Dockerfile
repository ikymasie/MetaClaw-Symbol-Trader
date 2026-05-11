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
# Ubuntu 22.04 — Python 3.11 + Node 20
# MT5 runs natively on the host (Windows or Wine on macOS);
# this container connects to it via RPyC over the network.
# ==========================================
FROM ubuntu:22.04 AS runner

ENV DEBIAN_FRONTEND=noninteractive
ENV NODE_ENV=production
ENV PYTHONUNBUFFERED=1
ENV NEXT_TELEMETRY_DISABLED=1

# 1. Basic utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates wget gnupg2 software-properties-common procps unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. Python 3.11
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 3. Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Default python3 -> python3.11
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Backend
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY backend/ ./

# Frontend
WORKDIR /app/frontend

COPY --from=frontend-builder /app/frontend/.next/standalone ./
COPY --from=frontend-builder /app/frontend/.next/static ./.next/static
COPY --from=frontend-builder /app/frontend/public ./public

# Entrypoint
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 3000 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
