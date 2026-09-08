"""
Base declarativa e mixins para os modelos SQLAlchemy.

Todos os modelos devem herdar de Base e, quando apropriado, dos mixins
aqui definidos. Isso garante consistência de campos e comportamentos.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bot.core.database import Base


class UUIDPrimaryKeyMixin:
    """Mixin que adiciona uma chave primária UUID v4."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )


class TimestampMixin:
    """Mixin que adiciona campos de criação e atualização automáticos."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin para exclusão lógica (soft delete)."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        self.deleted_at = None


class FullAuditMixin(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
):
    """
    Mixin completo: ID UUID, timestamps e soft delete.
    Uso recomendado para a maioria das entidades.
    """
    pass
