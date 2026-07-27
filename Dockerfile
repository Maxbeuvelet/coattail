# ── Stage 1: build the React dashboard ──────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime that serves API + dashboard ─────────────────────
FROM python:3.12-slim
WORKDIR /app

# Install backend deps (paper set — see requirements.txt)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Backend source
COPY backend/ backend/
# Built dashboard, placed where main.py expects it (../../frontend/dist)
COPY --from=frontend /app/frontend/dist frontend/dist

# SQLite lives on a mounted volume so data survives restarts/redeploys
ENV DB_PATH=/data/copybot.sqlite
ENV ENGINE_INTERVAL_SECONDS=30
VOLUME ["/data"]

WORKDIR /app/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
