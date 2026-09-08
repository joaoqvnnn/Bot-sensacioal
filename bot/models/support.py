"""
Modelos de suporte e atendimento.

Representam tickets de suporte abertos por usuários e as mensagens
trocadas dentro de cada ticket (com IA ou atendente humano).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class SupportTicket(FullAuditMixin):
    """
    Ticket de atendimento ao usuário.
    """

    __tablename__ = "support_tickets"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="support_tickets")

    # Usuário que abriu o ticket
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="support_tickets")

    # Status do ticket
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    # Valores: OPEN, WAITING_USER, WAITING_AGENT, RESOLVED, CLOSED

    # Assunto/título
    subject: Mapped[str] = mapped_column(String(150), nullable=False)

    # Indica se a IA está respondendo (True) ou se foi transferido para humano
    is_ai_handling: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Data de fechamento
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Mensagens do ticket
    messages = relationship("SupportMessage", back_populates="ticket", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SupportTicket(id={self.id}, user_id={self.user_id}, status={self.status})>"


class SupportMessage(FullAuditMixin):
    """
    Mensagem individual dentro de um ticket de suporte.
    """

    __tablename__ = "support_messages"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="support_messages")

    # Ticket associado
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket = relationship("SupportTicket", back_populates="messages")

    # Quem enviou a mensagem
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Valores: USER, AI, AGENT

    # Conteúdo
    content: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<SupportMessage(id={self.id}, ticket_id={self.ticket_id}, sender_type='{self.sender_type}')>"
