#!/usr/bin/env bash
# Запуск на Render: миграции, демо-данные (если SEED_DEMO=true), сервер.
set -euo pipefail

alembic upgrade head

if [ "${SEED_DEMO:-false}" = "true" ]; then
  python -m app.catalog.seed
fi

# --proxy-headers: Render стоит перед приложением как прокси и передаёт настоящий протокол (https)
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
