#!/usr/bin/env bash
# Запуск на Render: main.py сам применит миграции, загрузит демо-данные (SEED_DEMO=true)
# и поднимет сервер на 0.0.0.0:$PORT. Команда `python main.py` в настройках Render делает то же самое.
set -euo pipefail
exec python main.py
