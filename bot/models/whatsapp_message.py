"""
Modelo de mensagem WhatsApp enviada.

Representa uma mensagem enviada via WhatsApp Business API,
com status de entrega e conteúdo para histórico.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class WhatsAppMessage(FullAuditMixin):
    """
    Mensagem WhatsApp enviada ou recebida.
    """

    __tablename__ = "whatsapp_messages"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="whatsapp_messages")

    # Usuário destinatário (opcional)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user = relationship("User", back_populates="whatsapp_messages")

    # Número de telefone do destinatário
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # Conteúdo da mensagem
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Status: SENT, FAILED, DELIVERED, READ
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SENT")

    # ID externo da API (opcional)
    external_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Data de envio
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<WhatsAppMessage(id={self.id}, phone='{self.phone_number}', status='{self.status}')>"
