"""
Modelos de auditoria e anti-flood.

Representam logs de auditoria de ações administrativas/financeiras
e eventos de bloqueio por anti-flood, para rastreabilidade e segurança.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class AuditLog(FullAuditMixin):
    """
    Registro de auditoria de ações críticas no sistema.
    """

    __tablename__ = "audit_logs"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="audit_logs")

    # Ação realizada
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # Exemplos: "user.block", "wallet.credit", "product.price_change"

    # Descrição legível
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Usuário que executou a ação (se aplicável)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user = relationship("User", foreign_keys=[actor_user_id])

    # Usuário alvo da ação (se aplicável)
    target_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_user = relationship("User", foreign_keys=[target_user_id])

    # Dados adicionais em JSON (antes/depois, valores, etc.)
    metadata_json: Mapped[Optional[dict]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action='{self.action}', tenant_id={self.tenant_id})>"


class AntiFloodEvent(FullAuditMixin):
    """
    Evento de bloqueio por anti-flood de um usuário.
    """

    __tablename__ = "anti_flood_events"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="anti_flood_events")

    # Usuário bloqueado
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="anti_flood_events")

    # Tipo de gatilho (message, callback, inline, webapp)
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Quantidade de ações que excedeu o limite
    actions_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Intervalo de tempo em segundos
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    # Período de bloqueio (em segundos, 0 = permanente)
    block_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Data do bloqueio
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Data de desbloqueio (se temporário)
    unblock_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AntiFloodEvent(id={self.id}, user_id={self.user_id}, trigger='{self.trigger_type}')>"
