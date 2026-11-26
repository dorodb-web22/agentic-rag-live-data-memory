#!/usr/bin/env sh
set -eu

export PORT="${PORT:-8080}"

echo "[startup] Rendering Nginx config for PORT=${PORT}..."
envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default

if [ -n "${DATABASE_URL:-}" ]; then
  echo "[startup] Running Alembic database migrations..."
  alembic upgrade head
else
  echo "[startup] WARNING: DATABASE_URL not set; skipping alembic upgrade head."
fi

echo "[startup] Starting FastAPI (Uvicorn) on 127.0.0.1:8000..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips='*' &
UVICORN_PID=$!

# Forward termination signals cleanly
trap 'kill -TERM "${UVICORN_PID}" 2>/dev/null || true; exit 0' TERM INT

echo "[startup] Waiting for FastAPI health check..."
i=0
while [ "$i" -lt 40 ]; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "[startup] FastAPI is healthy."
    break
  fi
  i=$((i + 1))
  sleep 0.5
done

echo "[startup] Starting Nginx gateway on port ${PORT}..."
exec nginx -g "daemon off;"
