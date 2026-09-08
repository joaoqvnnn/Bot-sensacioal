"""
Modelo de usuário administrativo.

Representa um usuário com permissões administrativas em um tenant,
separando as funções de admin/dono do usuário comum, com papéis e status.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class AdminUser(FullAuditMixin):
    """
    Vínculo de usuário com papel administrativo em um tenant.
    """

    __tablename__ = "admin_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_admin_users_tenant_user"),
    )

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="admin_users")

    # Usuário que é admin
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="admin_roles")

    # Papel: ADMIN ou OWNER
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="ADMIN")

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Data de concessão
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Quem concedeu (opcional)
    granted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])

    def __repr__(self) -> str:
        return f"<AdminUser(id={self.id}, user_id={self.user_id}, role='{self.role}')>"
