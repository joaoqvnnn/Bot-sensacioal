"""
Modelo de notificação para usuários.

Representa uma notificação enviada a um usuário (Telegram, WhatsApp, e-mail),
com controle de status e idempotência para evitar duplicidade.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Notification(FullAuditMixin):
    """
    Notificação enviada ou a ser enviada a um usuário.
    """

    __tablename__ = "notifications"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="notifications")

    # Usuário destinatário (opcional, pode ser broadcast)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user = relationship("User", back_populates="notifications")

    # Canal de envio
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    # Valores: TELEGRAM, WHATSAPP, EMAIL

    # Tipo de notificação
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Exemplos: alert, broadcast, system, payment, delivery

    # Conteúdo
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, SENT, DELIVERED, FAILED, CANCELLED

    # Chave de idempotência
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Data de envio real
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type='{self.notification_type}', channel='{self.channel}', status='{self.status}')>"
