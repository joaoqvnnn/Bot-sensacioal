"""
Serviço de auditoria.

Fornece funções para registrar eventos críticos, como:
- Alterações de configuração
- Alterações de saldo (admin)
- Compras, pagamentos, saques, bloqueios, etc.

Nunca registra senhas ou tokens em texto aberto.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def audit_log(
    session: AsyncSession,
    tenant_id: UUID,
    action: str,
    description: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
    target_user_id: Optional[UUID] = None,
    metadata: Optional[dict] = None,
) -> AuditLog:
    """
    Cria um registro de auditoria.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        action: Ação realizada (ex: "wallet.credit", "user.block").
        description: Descrição legível.
        actor_user_id: ID do usuário que executou a ação.
        target_user_id: ID do usuário alvo (se aplicável).
        metadata: Dados adicionais (JSON) sem informações sensíveis.

    Returns:
        AuditLog: Registro criado.
    """
    # Remove qualquer campo sensível do metadata
    safe_metadata = None
    if metadata:
        safe_metadata = {
            k: v for k, v in metadata.items()
            if k not in ("password", "token", "secret", "access_token", "pix_code")
        }

    log = AuditLog(
        tenant_id=tenant_id,
        action=action,
        description=description,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        metadata_json=safe_metadata,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)

    logger.info(f"AuditLog criado: action={action}, tenant={tenant_id}")
    return log
