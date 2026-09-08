"""
Modelo de Usuário.

Representa qualquer pessoa que interage com o bot, seja cliente final,
administrador ou dono. Está sempre associado a um tenant (multi-tenancy).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class User(FullAuditMixin):
    """
    Entidade de usuário do sistema.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_id", name="uq_users_tenant_telegram"),
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="users")

    # Identificação no Telegram
    telegram_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Dados de contato
    whatsapp: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Status e papéis
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Segurança
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # para saque/ativação
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Datas relevantes
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relacionamentos
    wallet = relationship("Wallet", back_populates="user", uselist=False)
    ledger_entries = relationship("WalletLedger", back_populates="user")

    def __repr__(self) -> str:
        return f"<User(tenant_id={self.tenant_id}, telegram_id={self.telegram_id}, username='{self.username}')>"
