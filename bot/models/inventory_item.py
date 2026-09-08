"""
Modelo de Item de Estoque (InventoryItem).

Cada item representa uma unidade real de um produto (login, conta, etc.)
que pode ser vendida. O estoque é formado pela quantidade de itens
AVAILABLE (e RESERVED temporariamente). Dados sensíveis (email, senha, etc.)
são armazenados criptografados.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class InventoryItem(FullAuditMixin):
    """
    Entidade que representa um item de estoque de um produto.
    """

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_inventory_tenant_reference"),
    )

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="inventory_items")

    # Relacionamento com Product
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product = relationship("Product", back_populates="inventory_items")

    # Estado do item
    # Valores possíveis: AVAILABLE, RESERVED, SOLD
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")

    # Dados sensíveis criptografados (nunca em texto puro)
    email_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # referência pública/mascarada

    # Datas de reserva e expiração
    reserved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reservation_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # vencimento do serviço

    # Usuário que reservou/comprou (preenchido no momento da compra)
    reserved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sold_to_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relacionamentos opcionais para consultas
    reserved_by_user = relationship("User", foreign_keys=[reserved_by_user_id])
    sold_to_user = relationship("User", foreign_keys=[sold_to_user_id])

    def __repr__(self) -> str:
        return f"<InventoryItem(id={self.id}, product_id={self.product_id}, status={self.status})>"
