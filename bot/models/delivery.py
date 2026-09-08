"""
Modelos de entrega de produtos.

Representam as entregas realizadas após a compra (e-mail, WhatsApp, etc.),
com controle de status, tentativas e idempotência.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class DeliveryJob(FullAuditMixin):
    """
    Tarefa de entrega de um produto/serviço a um usuário.
    """

    __tablename__ = "delivery_jobs"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="delivery_jobs")

    # Pedido associado
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order = relationship("Order", back_populates="delivery_jobs")

    # Usuário destinatário
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="delivery_jobs")

    # Método de entrega
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    # Valores possíveis: TELEGRAM, WHATSAPP, EMAIL

    # Status da entrega
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, PROCESSING, SENT, DELIVERED, FAILED, CANCELLED

    # Chave de idempotência para evitar duplicidade
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Data da última tentativa
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Mensagem de erro (se houver)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relacionamento com tentativas
    attempts = relationship("DeliveryAttempt", back_populates="delivery_job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<DeliveryJob(id={self.id}, order_id={self.order_id}, method={self.method}, status={self.status})>"


class DeliveryAttempt(FullAuditMixin):
    """
    Tentativa individual de entrega dentro de um job.
    """

    __tablename__ = "delivery_attempts"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="delivery_attempts")

    # Job de entrega
    delivery_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("delivery_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_job = relationship("DeliveryJob", back_populates="attempts")

    # Status da tentativa
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, SENT, DELIVERED, FAILED

    # Mensagem de resultado ou erro
    result_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Data da tentativa
    attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<DeliveryAttempt(id={self.id}, delivery_job_id={self.delivery_job_id}, status={self.status})>"
