"""
Modelo de Usuário.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base, FullAuditMixin


class User(Base, FullAuditMixin):
    """Entidade de usuário do sistema."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_id", name="uq_users_tenant_telegram"),
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    whatsapp: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<User(tenant_id={self.tenant_id}, telegram_id={self.telegram_id}, username='{self.username}')>"
