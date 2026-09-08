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
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base, FullAuditMixin


class InventoryItem(Base, FullAuditMixin):
    """
    Entidade que representa um item de estoque de um produto.
    """

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_inventory_tenant_reference"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")

    email_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    reserved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reservation_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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

    def __repr__(self) -> str:
        return f"<InventoryItem(id={self.id}, product_id={self.product_id}, status={self.status})>"
