"""
Modelo de sessão de IA.

Representa uma conversa entre um usuário e a IA, registrando contexto,
uso de tokens e status, para fins de auditoria e controle.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class AISession(FullAuditMixin):
    """
    Sessão de conversa com IA.
    """

    __tablename__ = "ai_sessions"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="ai_sessions")

    # Usuário (se vinculado a uma conta)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user = relationship("User", back_populates="ai_sessions")

    # Canal de origem da conversa
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    # Valores: TELEGRAM, WHATSAPP

    # Identificador externo (chat_id do Telegram, número do WhatsApp, etc.)
    external_chat_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Contexto da conversa (histórico resumido ou prompt de sistema)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Total de tokens usados (se disponível)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status da sessão
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    # Valores: ACTIVE, COMPLETED, EXPIRED, CANCELLED

    # Data da última interação
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AISession(id={self.id}, channel='{self.channel}', status='{self.status}')>"
