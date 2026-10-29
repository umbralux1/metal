from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AdminLoginFailure(Base):
    """Неудачная попытка входа в админку. Живёт не дольше окна (specs/003-admin-login-limit)."""

    __tablename__ = "admin_login_failures"
    __table_args__ = (Index("ix_admin_login_failures_client_hash_created_at", "client_hash", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Отпечаток адреса подключения (app/leads/fingerprint.py); сам адрес, логин и пароль не храним
    client_hash: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
