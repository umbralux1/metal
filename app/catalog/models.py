import enum
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class Unit(enum.StrEnum):
    METER = "m"
    TON = "t"
    PIECE = "pcs"
    SQUARE_METER = "m2"

    @property
    def label(self) -> str:
        return {"m": "м", "t": "т", "pcs": "шт", "m2": "м²"}[self.value]


def _unit_enum() -> Enum:
    return Enum(
        Unit,
        name="unit",
        native_enum=False,
        length=8,
        values_callable=lambda e: [item.value for item in e],
        validate_strings=True,
    )


class SeoMixin:
    """Поля для ручного переопределения мета-тегов. Пусто — берётся шаблон из app/seo/meta.py."""

    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    h1: Mapped[str | None] = mapped_column(String(255))
    seo_text: Mapped[str | None] = mapped_column(Text)


class Category(TimestampMixin, SeoMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("parent_id", "slug", name="uq_categories_parent_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    # default="" — в админке поле необязательное: пустой slug собирается из названия
    slug: Mapped[str] = mapped_column(String(120), default="")
    # Полный путь без /catalog/: «armatura/a500c». По нему идёт роутинг.
    path: Mapped[str] = mapped_column(String(500), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent", order_by="Category.sort")

    @property
    def url(self) -> str:
        return f"/catalog/{self.path}/"

    def __str__(self) -> str:
        return f"{self.name} ({self.path})" if self.path else self.name or "Новый раздел"


class Product(TimestampMixin, SeoMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        Index(
            "ix_products_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    slug: Mapped[str] = mapped_column(String(160), default="")
    path: Mapped[str] = mapped_column(String(500), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    sku: Mapped[str | None] = mapped_column(String(64), unique=True)

    steel_grade: Mapped[str | None] = mapped_column(String(64), index=True)
    gost: Mapped[str | None] = mapped_column(String(64))
    diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), index=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    weight_per_m_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    base_unit: Mapped[Unit] = mapped_column(_unit_enum(), default=Unit.METER)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    category: Mapped[Category] = relationship(lazy="joined")
    prices: Mapped[list["Price"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def url(self) -> str:
        return f"/catalog/{self.path}/"

    def __str__(self) -> str:
        return self.name or "Новый товар"

    def price_for(self, unit: Unit) -> "Price | None":
        return next((p for p in self.prices if p.unit == unit), None)

    @property
    def base_price(self) -> "Price | None":
        return self.price_for(self.base_unit)

    @property
    def size_label(self) -> str:
        def fmt(value: Decimal) -> str:
            return f"{value.normalize():f}".replace(".", ",")

        if self.width_mm and self.height_mm:
            parts = [self.width_mm, self.height_mm] + ([self.thickness_mm] if self.thickness_mm else [])
            return "×".join(fmt(v) for v in parts)
        if self.diameter_mm:
            return f"Ø{fmt(self.diameter_mm)} мм"
        if self.thickness_mm:
            return f"{fmt(self.thickness_mm)} мм"
        return ""


class Price(Base):
    """Цена в копейках: целое число, без ошибок округления."""

    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("product_id", "unit", name="uq_prices_product_unit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    unit: Mapped[Unit] = mapped_column(_unit_enum())
    amount_kop: Mapped[int] = mapped_column(Integer)

    product: Mapped[Product] = relationship(back_populates="prices")

    def __str__(self) -> str:
        if self.amount_kop is None or self.unit is None:
            return "Новая цена"
        rub, kop = divmod(self.amount_kop, 100)
        whole = f"{rub:,}".replace(",", "\u00a0")
        return (f"{whole},{kop:02d}" if kop else whole) + f"\u00a0₽/{Unit(self.unit).label}"


class FilterLanding(TimestampMixin, SeoMixin, Base):
    """SEO-страница фильтра: раздел + набор значений, например «Арматура 12 мм»."""

    __tablename__ = "filter_landings"
    __table_args__ = (UniqueConstraint("category_id", "slug", name="uq_filter_landings_category_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(160), default="")
    path: Mapped[str] = mapped_column(String(500), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    # {"diameter_mm": 12} или {"width_mm": 40, "height_mm": 40}; список значений — условие IN
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_indexable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Создана генератором (app/catalog/landings.py) и обновляется им. Правка в админке делает её ручной.
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    category: Mapped[Category] = relationship(lazy="joined")

    @property
    def url(self) -> str:
        return f"/catalog/{self.path}/"

    def __str__(self) -> str:
        return self.name or "Новая посадочная"


class Redirect(TimestampMixin, Base):
    __tablename__ = "redirects"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_path: Mapped[str] = mapped_column(String(500), unique=True)
    to_path: Mapped[str] = mapped_column(String(500))
    status_code: Mapped[int] = mapped_column(Integer, default=301, server_default="301")

    def __str__(self) -> str:
        return f"{self.from_path} → {self.to_path}"
