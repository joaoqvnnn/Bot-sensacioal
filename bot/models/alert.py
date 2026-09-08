"""
Modelo de assinatura de alertas de estoque.

Representa o interesse de um usuário em ser notificado quando um
produto específico tiver novas unidades disponíveis.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class AlertSubscription(FullAuditMixin):
    """
    Assinatura de alerta de estoque de um produto para um usuário.
    """

    __tablename__ = "alerts_subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "product_id", name="uq_alerts_tenant_user_product"),
    )

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="alert_subscriptions")

    # Usuário que deseja ser notificado
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="alert_subscriptions")

    # Produto monitorado
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product = relationship("Product", back_populates="alert_subscriptions")

    # Status da assinatura
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Data da última notificação enviada (para controle de spam)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AlertSubscription(id={self.id}, user_id={self.user_id}, product_id={self.product_id})>"
