# ==========================================
# Stage 1: Build Frontend (Next.js)
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# Copy frontend package files
COPY frontend/package*.json ./
# Install dependencies
RUN npm ci

# Copy frontend source
COPY frontend/ ./
# Set environment variables for build
ENV NEXT_TELEMETRY_DISABLED=1

# Build Next.js application
RUN npm run build

# ==========================================
# Stage 2: Production Runner
# ==========================================
FROM python:3.9-slim AS runner
WORKDIR /app

# Install Node.js & runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV NODE_ENV=production
ENV PYTHONUNBUFFERED=1
ENV NEXT_TELEMETRY_DISABLED=1

# --- Setup Backend ---
WORKDIR /app/backend

# Copy backend requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# --- Setup Frontend ---
WORKDIR /app/frontend

# Copy the standalone Next.js build from builder
COPY --from=frontend-builder /app/frontend/.next/standalone ./
# Copy static assets
COPY --from=frontend-builder /app/frontend/.next/static ./.next/static
COPY --from=frontend-builder /app/frontend/public ./public

# --- Setup Entrypoint ---
WORKDIR /app
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# Expose ports for both services
EXPOSE 3000
EXPOSE 8000

# Start both services
ENTRYPOINT ["/app/docker-entrypoint.sh"]
