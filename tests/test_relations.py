"""Связи моделей не загружаются сами: у каждой `lazy="raise"`, нужное загружается явно в запросе.

Правило «Без N+1» в CLAUDE.md. Связь с `lazy="joined"` или `"selectin"` тянет данные при любом запросе модели,
даже где они не нужны; с `"raise"` забытая загрузка сразу падает в тестах, а не превращается в запрос на каждую
строку. Проверка модели, а не страницы, — исключение из правила «тесты через поведение», как у проверок базы.
"""

import app.models  # noqa: F401 — регистрирует все модели
from app.core.db import Base


def test_every_relationship_raises_instead_of_loading():
    loading = {
        f"{mapper.class_.__name__}.{rel.key}": rel.lazy
        for mapper in Base.registry.mappers
        for rel in mapper.relationships
        if rel.lazy != "raise"
    }
    assert loading == {}
