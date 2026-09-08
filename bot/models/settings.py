"""
Modelos de configurações editáveis e templates.

Incluem:
- Settings: chave-valor por tenant (configurações gerais)
- MessageTemplate: textos editáveis com placeholders
- KeyboardLayout: definição de botões e layouts
- MediaAsset: mídias salvas (imagens, etc.)
"""

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import FullAuditMixin


class Settings(FullAuditMixin):
    """
    Configuração chave-valor de um tenant.
    """

    __tablename__ = "settings"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="settings")

    # Chave única da configuração (ex: "support_link", "separator")
    key: Mapped[str] = mapped_column(String(100), nullable=False)

    # Valor (texto simples)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Valor JSON para configurações complexas
    value_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Settings(key='{self.key}', tenant_id={self.tenant_id})>"


class MessageTemplate(FullAuditMixin):
    """
    Template de mensagem editável com placeholders.
    """

    __tablename__ = "message_templates"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="message_templates")

    # Identificador do template (ex: "home", "catalog", "product")
    code: Mapped[str] = mapped_column(String(100), nullable=False)

    # Conteúdo editável
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Placeholders suportados (ex: "{user_id}, {balance}")
    # Pode ser uma lista JSON ou string separada por vírgula
    placeholders: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<MessageTemplate(code='{self.code}', tenant_id={self.tenant_id})>"


class KeyboardLayout(FullAuditMixin):
    """
    Definição de botões e layout de teclado inline.
    """

    __tablename__ = "keyboard_layouts"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="keyboard_layouts")

    # Código do teclado (ex: "main_menu", "profile")
    code: Mapped[str] = mapped_column(String(100), nullable=False)

    # Dados dos botões em JSON estruturado
    buttons_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Layout: row_width padrão
    row_width: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    def __repr__(self) -> str:
        return f"<KeyboardLayout(code='{self.code}', tenant_id={self.tenant_id})>"


class MediaAsset(FullAuditMixin):
    """
    Mídia salva (imagens, vídeos) para uso em mensagens e produtos.
    """

    __tablename__ = "media_assets"

    # Tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant = relationship("Tenant", back_populates="media_assets")

    # Nome/descrição
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    # Tipo de mídia (image, video, etc.)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # URL ou caminho da mídia
    url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Tamanho (opcional)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<MediaAsset(id={self.id}, name='{self.name}', type='{self.media_type}')>"
