"""
Modelos de pedido e item de pedido.

Representam uma compra realizada por um usuário e os itens adquiridos.
Todos os valores são armazenados em centavos (inteiro) para evitar
problemas com ponto flutuante.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Order(FullAuditMixin):
    """
    Pedido realizado por um usuário.
    """

    __tablename__ = "orders"

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="orders")

    # Relacionamento com Usuário (comprador)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="orders")

    # Status do pedido
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores possíveis: PENDING, PAID, COMPLETED, CANCELLED, FAILED

    # Total pago (em centavos)
    total_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False, default=0)

    # Datas
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Itens do pedido
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, user_id={self.user_id}, status={self.status}, total={self.total_cents})>"


class OrderItem(FullAuditMixin):
    """
    Item individual dentro de um pedido.
    """

    __tablename__ = "order_items"

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="order_items")

    # Relacionamento com Order
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order = relationship("Order", back_populates="items")

    # Relacionamento com Product (produto comprado)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product = relationship("Product", back_populates="order_items")

    # Relacionamento com InventoryItem (estoque vendido)
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    inventory_item = relationship("InventoryItem", back_populates="order_item")

    # Preço unitário pago (em centavos)
    unit_price_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)

    # Quantidade (geralmente 1, mas pode ser >1)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Nome/descrição do produto no momento da compra (para histórico)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    product_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, product_id={self.product_id}, qty={self.quantity})>"
