"""
Modelos de transmissão e notificações programadas.

Representam mensagens em massa enviadas pelo administrador e
notificações agendadas para execução futura.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Broadcast(FullAuditMixin):
    """
    Transmissão de mensagem em massa para usuários.
    """

    __tablename__ = "broadcasts"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="broadcasts")

    # Título/descrição interna (para controle)
    title: Mapped[str] = mapped_column(String(150), nullable=False)

    # Conteúdo da mensagem
    message_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Mídia opcional
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Status da transmissão
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, SENDING, COMPLETED, FAILED, CANCELLED

    # Público-alvo (opcional)
    target_all: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Datas
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Broadcast(id={self.id}, title='{self.title}', status={self.status})>"


class ScheduledNotification(FullAuditMixin):
    """
    Notificação agendada para execução futura, com ou sem repetição.
    """

    __tablename__ = "scheduled_notifications"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="scheduled_notifications")

    # Título/descrição
    title: Mapped[str] = mapped_column(String(150), nullable=False)

    # Conteúdo
    message_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Mídia opcional
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Data e hora de execução
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Repetição (opcional)
    repeat_interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repeat_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    # Valores: PENDING, PROCESSING, COMPLETED, CANCELLED

    # Última execução
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ScheduledNotification(id={self.id}, title='{self.title}', run_at={self.run_at})>"
