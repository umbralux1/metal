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

## Деплой на Render

В репозитории лежит Blueprint `render.yaml`: по нему Render создаёт веб-сервис и базу PostgreSQL 16.

1. Залейте проект на GitHub (или GitLab): `git remote add origin …` и `git push -u origin main`.
2. На [dashboard.render.com](https://dashboard.render.com): **New → Blueprint**, выберите репозиторий, нажмите **Apply**.
   Render спросит `PHONE` и `EMAIL` — их видно на сайте.
3. Через пару минут сайт откроется по адресу вида `https://metal-web.onrender.com`.

При каждом запуске `scripts/render-start.sh` применяет миграции (`alembic upgrade head`),
при `SEED_DEMO=true` загружает демо-товары и запускает uvicorn. Каждый push в `main` деплоится автоматически.

Пока сайт живёт на `*.onrender.com`, он закрыт от поисковиков (`ALLOW_INDEXING=false`): robots.txt запрещает
всё, а каждый ответ получает `X-Robots-Tag: noindex`. Это нужно, чтобы тестовая копия не попала в индекс
раньше основного домена. Когда подключите свой домен (Settings → Custom Domains), поменяйте в Environment:
`SITE_URL=https://ваш-домен.ru`, `ALLOW_INDEXING=true`, `SEED_DEMO=false`.

Ограничения бесплатного тарифа Render ([подробнее](https://render.com/docs/free)):
- веб-сервис засыпает после 15 минут без запросов, первый запрос после сна идёт медленно;
- бесплатная база PostgreSQL удаляется через 30 дней после создания.

Для настоящего запуска поменяйте в `render.yaml` `plan: free` на платные планы: веб-сервис — `0.5c-512mb` или выше,
база — `0.1c-256mb` или выше. Адрес базы Render отдаёт в виде `postgresql://…`, приложение само переключает его
на драйвер psycopg; `SITE_URL` без явного значения берётся из `RENDER_EXTERNAL_URL`.

## Структура

```
app/
  main.py              приложение, 404 с проверкой таблицы редиректов
  core/                настройки (.env), подключение к БД, шаблонизатор, меню разделов
  catalog/
    models.py          Category, Product, Price, FilterLanding, Redirect
    repository.py      запросы каталога, фильтры посадочных
    router.py          /catalog/ и /catalog/{path}/ — раздел, посадочная или товар; /api/calc/{id}/
    calculator.py      расчёт заказа: штуки / метры / кг, резка, цена
    seed.py            демо-данные
    drawings.py        чертежи сечений и значки разделов (SVG)
    utils.py           slugify, нормализация текста для поиска
  seo/
    meta.py            шаблоны title / description / H1, canonical, robots
    jsonld.py          BreadcrumbList, ItemList, Product, Organization
    middleware.py      301 на канонический URL (регистр, слеш, //)
    router.py          robots.txt, sitemap.xml
  leads/               заявки: модель, POST /api/lead/, уведомления
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

## Калькулятор и заявки

На карточке товара — расчёт заказа: количество в штуках, метрах или килограммах, резка в размер.
Логика — чистые функции в `app/catalog/calculator.py`, деньги в копейках.

- Без резки количество округляется до целых прутков (длина из `Product.length_m`).
- С резкой считается раскрой: сколько прутков нужно, сколько резов и сколько остаётся в обрезках.
  Если отрезки делят пруток без остатка, последний отрезок получается без реза.
- От `TON_PRICE_FROM_KG` (по умолчанию 1000 кг) действует цена за тонну, если она есть.
- Пересчёт на лету: `static/js/calc.js` запрашивает `/api/calc/{id}/` и подставляет кусок HTML.
  Без JavaScript форма работает обычным GET на страницу товара (такие адреса получают `noindex`).
- Заявка (`POST /api/lead/`) пересчитывается на сервере, сохраняется в таблицу `leads` со снимком расчёта
  и пишется в лог `metal.leads`. Отправку в Telegram или на почту подключать в `app/leads/notify.py`.
- Защита от ботов — скрытое поле-ловушка `website`. Телефон приводится к виду `+7XXXXXXXXXX`.

Настройки: `CUT_PRICE_KOP` (цена реза в копейках, по умолчанию 5000 = 50 ₽), `TON_PRICE_FROM_KG`.

## Внешний вид

- Шрифт Golos Text (OFL) лежит локально: `app/static/fonts/golos-text.woff`, кириллица и латиница, все веса в одном файле.
- Цвета и размеры — CSS-переменные в начале `app/static/css/main.css`.
- Фирменный элемент — чертёж сечения (`app/catalog/drawings.py`): строится из размеров товара,
  со штриховкой разреза и размерными линиями. Профиль угадывается по полям или задаётся в `attrs["profile"]`
  (`rebar`, `round`, `tube_rect`, `plate`). Значки разделов — там же, по slug корневого раздела.
- На телефоне таблица товаров превращается в карточки, внизу экрана — панель «Позвонить / мессенджер / Каталог».
- Поиск `/search/?q=` ищет по `search_text` (все слова запроса), сортирует по похожести через pg_trgm; страница закрыта от индексации.

## SEO-правила, которые держат тесты

- каждая страница из sitemap отдаёт 200, один H1, canonical на себя, без noindex;
- `?sort=…`, любые параметры и страницы пагинации 2+ — `noindex, follow`, canonical на чистый адрес;
- `/Catalog/Armatura`, `/catalog/armatura`, `/catalog//armatura/` → 301 на `/catalog/armatura/`;
- закрытые комбинации фильтров не попадают в sitemap.

## Дальше по плану

- импорт прайса XLSX (openpyxl + валидация Pydantic), пересчёт цен;
- админка (SQLAdmin): товары, цены, SEO-поля, посадочные, редиректы;
- корзина на основе калькулятора, оформление заказа (физлицо / юрлицо), отправка заявок в Telegram;
- поиск по `search_text` через pg_trgm; калькуляторы веса; служебные страницы.
