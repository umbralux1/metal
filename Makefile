# Частые команды проекта. Список с описаниями: make (или make help).
# Нужны Docker (база в контейнере) и Python 3.11+. Виртуальное окружение — папка venv.

VENV ?= venv
PY = $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help setup venv install browsers env db db-stop db-logs db-shell db-reset migrate migration seed landings \
        run test lint types imports audit format check snapshot snapshot-diff dups mutants deploy clean

help: ## Список команд
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

# ---------- Первый запуск ----------

setup: venv install browsers env db migrate seed ## Всё с нуля: окружение, зависимости, браузер для тестов, .env, база, демо-товары
	@echo "Готово. Запуск: make run → http://127.0.0.1:8000"

venv: ## Создать виртуальное окружение venv (если его нет)
	@test -x $(VENV)/bin/python || python3 -m venv $(VENV)

install: ## Установить зависимости (requirements-dev.txt)
	$(VENV)/bin/python -m pip install -r requirements-dev.txt

browsers: ## Браузер WebKit (движок Safari) для браузерных тестов, один раз после install
	$(PY) -m playwright install webkit

env: ## Создать .env из .env.example (существующий не трогает)
	@test -f .env && echo ".env уже есть — не трогаю" || (cp .env.example .env && echo "Создан .env — впишите свои данные")

# ---------- База данных ----------

db: ## Запустить PostgreSQL в Docker и дождаться готовности
	$(COMPOSE) up -d --wait db

db-stop: ## Остановить базу (данные сохраняются)
	$(COMPOSE) stop db

db-logs: ## Логи базы
	$(COMPOSE) logs -f --tail=100 db

db-shell: ## Консоль psql в базе metal
	$(COMPOSE) exec db psql -U metal metal

db-reset: ## УДАЛИТЬ базу со всеми данными и создать заново с демо-товарами
	@read -p "Удалить локальную базу со всеми товарами и заявками? Напишите yes: " ok && [ "$$ok" = yes ] || (echo "Отменено"; exit 1)
	$(COMPOSE) down -v
	$(MAKE) db migrate seed

migrate: ## Применить миграции (alembic upgrade head)
	$(PY) -m alembic upgrade head

migration: ## Новая миграция по изменениям моделей: make migration m="add stock"
	@test -n "$(m)" || (echo "Укажите описание: make migration m=\"что изменилось\""; exit 1)
	$(PY) -m alembic revision --autogenerate -m "$(m)"
	@echo "Проверьте созданный файл в migrations/versions/ перед make migrate"

seed: ## Загрузить демо-каталог (только недостающее) и обновить посадочные
	$(PY) -m app.catalog.seed

landings: ## Обновить посадочные «по размеру» из каталога
	$(PY) -m app.catalog.landings

# ---------- Работа ----------

run: db ## Запустить сайт локально (база поднимется сама)
	$(PY) main.py

test: db ## Тесты (pytest)
	$(PY) -m pytest

lint: ## Проверка кода и оформления (ruff check, ruff format --check)
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

types: ## Проверка типов (mypy): строго для новых модулей
	$(PY) -m mypy

imports: ## Контракты зависимостей модулей (import-linter)
	$(PY) -c "import sys; from importlinter.cli import lint_imports_command; sys.exit(lint_imports_command())"

audit: ## Известные уязвимости в зависимостях (pip-audit, нужен интернет)
	$(PY) -m pip_audit -r requirements.txt

format: ## Привести оформление кода к ruff (миграции не трогает — исключены в pyproject.toml)
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

check: lint types imports test ## Всё, что проверяем перед коммитом: ruff, mypy, import-linter, pytest

snapshot: db ## Снимок сайта, корзины и админки до рефакторинга (база metal_snapshot, .snapshots/before)
	$(PY) -m scripts.snapshot before

snapshot-diff: db ## Снимок после изменений и сравнение с make snapshot: какие ответы поменялись
	$(PY) -m scripts.snapshot diff

dups: ## Похожий код (semdup, нужен Rust): отчёт в semdup-085.txt — кандидаты, разбирать глазами
	@command -v semdup >/dev/null || (echo "Нужен semdup: cargo install semdup --locked (см. docs/tech-debt.md)"; exit 1)
	semdup scan -t 0.85 --show-bodies > semdup-085.txt
	@echo "Отчёт: semdup-085.txt ($$(grep -c '^## cluster' semdup-085.txt) кластеров)"

mutants: ## Мутационное тестирование части сайта: make mutants M=cart, M="cart leads", M=catalog/calculator, M=all
	@if [ -n "$(M)" ]; then $(MAKE) --no-print-directory db; fi
	$(PY) -m scripts.mutants $(M)

# ---------- Выкладка ----------

deploy: check ## Проверить и выложить на Render: git push в main (Render деплоит сам)
	@test -z "$$(git status --porcelain)" || (echo "Есть незакоммиченные изменения — сначала git commit"; git status --short; exit 1)
	@test "$$(git rev-parse --abbrev-ref HEAD)" = main || (echo "Выкладка только из ветки main"; exit 1)
	git push origin main
	@echo "Отправлено. Render начнёт сборку сам — статус: https://dashboard.render.com"

clean: ## Удалить кэши Python, pytest и ruff
	find . -name __pycache__ -type d -not -path "./$(VENV)/*" -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
