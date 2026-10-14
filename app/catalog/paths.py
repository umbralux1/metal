"""Адреса страниц каталога и 301-редиректы при их изменении.

Путь хранится целиком («armatura/a500c/armatura-12-mm-a500s»), поэтому при переименовании раздела
меняются адреса всех вложенных разделов, посадочных и товаров. Старые адреса уходят в таблицу redirects,
чтобы проиндексированные ссылки не превратились в 404.
"""

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Category, FilterLanding, Product, Redirect


def url(path: str) -> str:
    return f"/catalog/{path}/"


async def parent_path(session: AsyncSession, category_id: int | str | None) -> str | None:
    if not category_id:
        return None
    return await session.scalar(select(Category.path).where(Category.id == int(category_id)))


async def path_taken(session: AsyncSession, path: str, *, exclude: object | None = None) -> bool:
    """Занят ли адрес другим разделом, посадочной или товаром (у каждого адреса — одна страница)."""
    for model in (Category, FilterLanding, Product):
        stmt = select(model.id).where(model.path == path)
        if exclude is not None and isinstance(exclude, model) and exclude.id is not None:
            stmt = stmt.where(model.id != exclude.id)
        if await session.scalar(stmt):
            return True
    return False


async def add_redirect(session: AsyncSession, old_path: str, new_path: str) -> None:
    """Редирект old → new; старые цепочки на old переводим сразу на new, петли убираем."""
    old_url, new_url = url(old_path), url(new_path)
    if old_url == new_url:
        return
    await session.execute(update(Redirect).where(Redirect.to_path == old_url).values(to_path=new_url))
    # Если вернули прежний адрес — старый редирект с него больше не нужен
    for stale in await session.scalars(select(Redirect).where(Redirect.from_path == new_url)):
        await session.delete(stale)
    existing = await session.scalar(select(Redirect).where(Redirect.from_path == old_url))
    if existing:
        existing.to_path = new_url
    else:
        session.add(Redirect(from_path=old_url, to_path=new_url, status_code=301))
    # Самоссылки после переписывания цепочек
    for loop in await session.scalars(select(Redirect).where(Redirect.from_path == Redirect.to_path)):
        await session.delete(loop)


async def move_tree(session: AsyncSession, old_prefix: str, new_prefix: str) -> int:
    """Раздел сменил адрес: переписываем пути всего, что внутри, и ставим редиректы. Возвращает число страниц."""
    if old_prefix == new_prefix:
        return 0
    moved = 0
    for model in (Category, FilterLanding, Product):
        rows = (
            await session.execute(
                select(model.id, model.path).where(model.path.startswith(old_prefix + "/", autoescape=True))
            )
        ).all()
        for row_id, old_path in rows:
            new_path = new_prefix + old_path[len(old_prefix) :]
            await session.execute(update(model).where(model.id == row_id).values(path=new_path))
            await add_redirect(session, old_path, new_path)
            moved += 1
    return moved


async def count_children(session: AsyncSession, category: Category) -> int:
    """Сколько страниц внутри раздела — чтобы не удалить раздел вместе с каталогом."""
    total = 0
    for model in (Category, FilterLanding, Product):
        total += (
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(or_(model.path.startswith(category.path + "/", autoescape=True)))
            )
            or 0
        )
    return total
