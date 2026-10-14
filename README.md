# Металлобаза — интернет-магазин металлопроката

FastAPI + PostgreSQL 16, серверный рендеринг (Jinja2), SEO-каталог с посадочными страницами по типоразмерам.

## Запуск

Нужны Python 3.11+ и Docker Desktop (или OrbStack).

```bash
cp .env.example .env
docker compose up -d                     # PostgreSQL 16 на localhost:5433 + база metal_test для тестов
source venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head                     # создать таблицы
python -m app.catalog.seed               # демо-данные: арматура и профильная труба
python main.py                           # http://127.0.0.1:8000
pytest                                   # тесты, в т. ч. SEO-контракт
```

Документация API (`/docs`) включается только при `DEBUG=true`.

## Структура

```
app/
  main.py              приложение, 404 с проверкой таблицы редиректов
  core/                настройки (.env), подключение к БД, шаблонизатор
  catalog/
    models.py          Category, Product, Price, FilterLanding, Redirect
    repository.py      запросы каталога, фильтры посадочных
    router.py          /catalog/ и /catalog/{path}/ — раздел, посадочная или товар
    seed.py            демо-данные
    utils.py           slugify, нормализация текста для поиска
  seo/
    meta.py            шаблоны title / description / H1, canonical, robots
    jsonld.py          BreadcrumbList, ItemList, Product, Organization
    middleware.py      301 на канонический URL (регистр, слеш, //)
    router.py          robots.txt, sitemap.xml
  pages/router.py      главная, /health
  templates/, static/
migrations/            Alembic
tests/                 pytest: SEO-контракт и утилиты
```

## Как устроен каталог

Один роут `/catalog/{path}/` ищет по пути сначала раздел (`Category`), потом SEO-страницу фильтра
(`FilterLanding`), потом товар (`Product`). Не нашёл — 404, но сначала проверяется таблица `redirects`.

- **Раздел** показывает товары своих подразделов (по префиксу пути) и ссылки на посадочные «по размеру».
- **FilterLanding** = раздел + фильтр в JSON: `{"diameter_mm": 12}` или `{"width_mm": 40, "height_mm": 40}`;
  список значений даёт условие IN. Допустимые ключи — `FILTERABLE_COLUMNS` в `repository.py`.
  `is_indexable=false` — страница работает, но получает `noindex` и не попадает в sitemap.
- **Цены** хранятся в копейках (`Price.amount_kop`) отдельно по единицам: метр, тонна, штука.
  «От N ₽» в title считается по базовой единице товара.
- **Мета-теги**: если в записи заполнены `title`, `description`, `h1` — берутся они, иначе шаблон из `seo/meta.py`.

## SEO-правила, которые держат тесты

- каждая страница из sitemap отдаёт 200, один H1, canonical на себя, без noindex;
- `?sort=…`, любые параметры и страницы пагинации 2+ — `noindex, follow`, canonical на чистый адрес;
- `/Catalog/Armatura`, `/catalog/armatura`, `/catalog//armatura/` → 301 на `/catalog/armatura/`;
- закрытые комбинации фильтров не попадают в sitemap.

## Дальше по плану

- импорт прайса XLSX (openpyxl + валидация Pydantic), пересчёт цен;
- админка (SQLAdmin): товары, цены, SEO-поля, посадочные, редиректы;
- корзина с расчётом метража и веса, оформление заказа (физлицо / юрлицо), отправка в Telegram;
- поиск по `search_text` через pg_trgm; калькуляторы веса; служебные страницы.
