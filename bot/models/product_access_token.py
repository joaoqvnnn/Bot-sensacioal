"""
Modelo de token de acesso a produto.

Representa um token temporário de uso único ou limitado, vinculado a um
pedido/item, usado para ativar/consultar o produto no website ou WhatsApp.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class ProductAccessToken(FullAuditMixin):
    """
    Token de acesso para ativação/consulta de produto.
    """

    __tablename__ = "product_access_tokens"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="product_access_tokens")

    # Usuário dono do token
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="product_access_tokens")

    # Pedido associado
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order = relationship("Order", back_populates="product_access_tokens")

    # Item do pedido (opcional)
    order_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    order_item = relationship("OrderItem", back_populates="product_access_token")

    # Token gerado (hash armazenado, nunca token puro)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    # Valores: ACTIVE, USED, EXPIRED, REVOKED

    # Data de expiração
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Data de uso
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ProductAccessToken(id={self.id}, order_id={self.order_id}, status='{self.status}')>"
