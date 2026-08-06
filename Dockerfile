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

# Install backend deps. The live set is included so LIVE_TRADING can be armed
# without rebuilding a different image; installing the SDK does not by itself
# place any orders — that still needs LIVE_TRADING plus credentials.
COPY backend/requirements.txt backend/requirements.txt
COPY backend/requirements-live.txt backend/requirements-live.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
 && pip install --no-cache-dir -r backend/requirements-live.txt

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
