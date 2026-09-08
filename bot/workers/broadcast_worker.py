"""
Worker de transmissões em massa.

Processa a fila de Broadcasts pendentes, enviando mensagens para
todos os usuários ativos do tenant, respeitando:
- Velocidade de envio (mensagens por segundo)
- Retry automático em falhas
- Status de controle (PENDING, SENDING, PAUSED, COMPLETED, CANCELLED)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.core.redis import create_redis_client, close_redis_client
from bot.core.config import settings
from bot.models.broadcast import Broadcast
from bot.models.user import User
from bot.models.settings import Settings

logger = logging.getLogger(__name__)


async def process_broadcast_task(
    ctx: Dict[str, Any],
    tenant_id: str,
    broadcast_id: str,
    bot=None,
) -> bool:
    """
    Processa uma transmissão específica.

    Args:
        ctx: Contexto do arq.
        tenant_id: ID do tenant (string).
        broadcast_id: ID do broadcast (string).
        bot: Instância do Bot para envio (opcional, se não fornecido, tenta criar).

    Returns:
        bool: True se concluído com sucesso.
    """
    async with get_async_session_factory() as session:
        # Busca broadcast
        stmt = select(Broadcast).where(
            Broadcast.tenant_id == UUID(tenant_id),
            Broadcast.id == UUID(broadcast_id),
            Broadcast.deleted_at.is_(None),
        )
        broadcast = (await session.execute(stmt)).scalar_one_or_none()

        if broadcast is None:
            logger.error(f"Broadcast {broadcast_id} não encontrado.")
            return False

        if broadcast.status not in ("PENDING", "PAUSED"):
            logger.info(f"Broadcast {broadcast_id} não está pendente/pausado (status={broadcast.status}).")
            return True

        # Marca como enviando
        broadcast.status = "SENDING"
        await session.commit()

        # Busca usuários alvo (todos ativos)
        user_stmt = select(User).where(
            User.tenant_id == UUID(tenant_id),
            User.is_blocked == False,
            User.deleted_at.is_(None),
        )
        users = (await session.execute(user_stmt)).scalars().all()

        if not users:
            broadcast.status = "COMPLETED"
            await session.commit()
            logger.info("Nenhum usuário para enviar. Broadcast concluído.")
            return True

        # Obtém velocidade e retry configurados
        speed_per_second = int(await _get_setting(session, UUID(tenant_id), "broadcast_speed_per_second") or "5")
        retry_count = int(await _get_setting(session, UUID(tenant_id), "broadcast_retry") or "3")

        # Processa envio
        sent = 0
        failed = 0
        interval = 1.0 / speed_per_second if speed_per_second > 0 else 0.05

        for user in users:
            if broadcast.status == "CANCELLED":
                break
            if broadcast.status == "PAUSED":
                break  # para se for pausado externamente

            success = await _send_to_user(bot, user, broadcast)

            if success:
                sent += 1
            else:
                # Tenta retry
                for attempt in range(1, retry_count + 1):
                    await asyncio.sleep(interval * attempt)  # backoff simples
                    success = await _send_to_user(bot, user, broadcast)
                    if success:
                        sent += 1
                        failed -= 0  # mantém contagem
                        break
                if not success:
                    failed += 1

            # Aguarda intervalo entre mensagens
            await asyncio.sleep(interval)

        # Atualiza status final
        broadcast.status = "COMPLETED" if failed == 0 else "COMPLETED_WITH_ERRORS"
        broadcast.sent_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info(
            f"Broadcast {broadcast_id} processado: {sent} enviados, {failed} falhas."
        )
        return True


async def _send_to_user(bot, user: User, broadcast: Broadcast) -> bool:
    """
    Envia a transmissão para um usuário específico.

    Args:
        bot: Instância do Bot.
        user: Destinatário.
        broadcast: Broadcast a enviar.

    Returns:
        bool: True se enviado com sucesso.
    """
    if bot is None:
        logger.warning("Bot não fornecido; não é possível enviar.")
        return False

    try:
        from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

        if broadcast.image_url:
            await bot.send_photo(user.telegram_id, broadcast.image_url, caption=broadcast.message_text)
        elif broadcast.video_url:
            await bot.send_video(user.telegram_id, broadcast.video_url, caption=broadcast.message_text)
        else:
            await bot.send_message(user.telegram_id, broadcast.message_text)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        logger.warning(f"Falha ao enviar para user_id={user.telegram_id} (bloqueado ou ID inválido).")
        return False
    except Exception as e:
        logger.exception(f"Erro ao enviar para user_id={user.telegram_id}: {e}")
        return False


async def _get_setting(session, tenant_id: UUID, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None
