"""
Serviço de usuário.

Contém funções para gerenciar usuários, verificar assinatura de canal,
criar/obter registros no banco e aplicar regras de bloqueio.

Todas as operações são assíncronas e usam a sessão do SQLAlchemy.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.config import settings
from bot.models.user import User
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def get_or_create_user(
    session: AsyncSession,
    tenant: Tenant,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> User:
    """
    Obtém um usuário existente ou cria um novo para o tenant e telegram_id.

    Args:
        session: Sessão do banco.
        tenant: Tenant ao qual o usuário pertence.
        telegram_id: ID do Telegram.
        username: Username atual (pode ser atualizado).
        first_name: Primeiro nome.
        last_name: Sobrenome.

    Returns:
        User: Instância do usuário (já salva, se criada).
    """
    stmt = select(User).where(
        User.tenant_id == tenant.id,
        User.telegram_id == telegram_id,
        User.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            tenant_id=tenant.id,
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            registered_at=datetime.now(timezone.utc),
            is_blocked=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info(f"Novo usuário criado: telegram_id={telegram_id}, tenant={tenant.slug}")
    else:
        # Atualiza dados caso tenham mudado
        if user.username != username:
            user.username = username
        if user.first_name != first_name:
            user.first_name = first_name
        if user.last_name != last_name:
            user.last_name = last_name
        await session.commit()
        await session.refresh(user)

    return user


async def is_user_blocked(user: User) -> bool:
    """
    Verifica se o usuário está bloqueado.

    Args:
        user: Instância do usuário.

    Returns:
        bool: True se bloqueado.
    """
    return user.is_blocked


async def check_channel_membership(
    bot: Bot,
    tenant: Tenant,
    telegram_id: int,
) -> bool:
    """
    Verifica se o usuário é membro do canal obrigatório configurado para o tenant.

    O canal é definido nas configurações do tenant (settings_json ou coluna dedicada).
    Por enquanto, usaremos a configuração global de settings (SUPPORT_CHAT_LINK)
    como fallback, mas a verificação real exige um canal configurado.

    Args:
        bot: Instância do Bot.
        tenant: Tenant atual.
        telegram_id: ID do Telegram do usuário.

    Returns:
        bool: True se for membro ou se não houver canal configurado.
    """
    # TODO: Buscar canal obrigatório do tenant (tabela settings ou settings_json).
    # Por enquanto, assume que o canal é armazenado em settings_json como "mandatory_channel".
    # Se não houver canal configurado, retorna True (sem restrição).
    import json
    channel_id = None
    if tenant.settings_json:
        try:
            tenant_settings = json.loads(tenant.settings_json)
            channel_id = tenant_settings.get("mandatory_channel")
        except Exception:
            channel_id = None

    if not channel_id:
        # Se não houver canal, libera acesso (comportamento padrão)
        logger.warning(f"Tenant {tenant.slug} não possui canal obrigatório configurado.")
        return True

    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=telegram_id)
        # Status "left" ou "kicked" indicam não-membro
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.error(f"Erro ao verificar membro do canal {channel_id}: {e}")
        return False


async def get_tenant_for_bot(session: AsyncSession, bot_username: str) -> Optional[Tenant]:
    """
    Obtém o tenant associado ao bot atual, usando o username do bot.

    Args:
        session: Sessão do banco.
        bot_username: Username do bot (sem @).

    Returns:
        Tenant: Tenant correspondente ou None.
    """
    # Por enquanto, a associação bot->tenant pode ser via settings ou coluna futura.
    # Como ainda não temos uma coluna específica, retornamos o primeiro tenant ativo.
    stmt = select(Tenant).where(
        Tenant.is_active == True,
        Tenant.deleted_at.is_(None),
    ).order_by(Tenant.created_at.asc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
