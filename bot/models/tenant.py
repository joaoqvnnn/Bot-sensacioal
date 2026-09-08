"""
Modelo de Tenant (cliente multi-tenant).

Cada tenant representa um cliente que aluga/usa uma instância do bot,
com seus próprios usuários, produtos, estoque, pagamentos, etc.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base, FullAuditMixin


class Tenant(Base, FullAuditMixin):
    """
    Entidade que representa um cliente/tenant do sistema.
    """

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    # Identificação
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status e plano
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    plan: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Configurações específicas do tenant
    settings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relacionamentos
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    wallets = relationship("Wallet", back_populates="tenant", cascade="all, delete-orphan")
    wallet_ledger_entries = relationship("WalletLedger", back_populates="tenant", cascade="all, delete-orphan")

    categories = relationship("Category", back_populates="tenant", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="tenant", cascade="all, delete-orphan")
    inventory_items = relationship("InventoryItem", back_populates="tenant", cascade="all, delete-orphan")

    def is_expired(self) -> bool:
        """Retorna True se o tenant estiver vencido."""
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now(self.expires_at.tzinfo)

    def is_available(self) -> bool:
        """Retorna True se o tenant estiver ativo e não vencido."""
        return self.is_active and not self.is_expired()

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name='{self.name}', slug='{self.slug}')>"
