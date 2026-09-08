"""
Modelo de Produto.

Representa um serviço/produto comercializado no catálogo.
Pertence a uma categoria e a um tenant, com preço em centavos.
"""

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Product(FullAuditMixin):
    """
    Entidade de produto/serviço disponível para compra.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_products_tenant_name"),
    )

    # Relacionamento com Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="products")

    # Relacionamento com Category
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category = relationship("Category", back_populates="products")

    # Identificação e descrição
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Preço em centavos (inteiro, jamais float)
    price_cents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False, default=0)

    # Duração e garantia
    duration_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    guarantee_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status e ordem
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Limite de compra por usuário (0 = sem limite)
    max_per_user: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Estoque agregado (será calculado pela contagem de inventory_items disponíveis)
    # Não armazenamos contagem diretamente; usamos relacionamento e query.
    inventory_items = relationship("InventoryItem", back_populates="product")

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', price_cents={self.price_cents})>"
