import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.scheduled_notification import ScheduledNotification
from bot.models.audit_log import AuditLog
from bot.models.user import User

logger = logging.getLogger(__name__)


async def schedule_notification(
    session: AsyncSession,
    tenant_id: UUID,
    title: str,
    message_text: str,
    run_at: datetime,
    repeat_interval_minutes: Optional[int] = None,
    repeat_until: Optional[datetime] = None,
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    timezone_str: str = "UTC",
) -> ScheduledNotification:
    """
    Cria uma notificação programada.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        title: Título interno.
        message_text: Texto da notificação.
        run_at: Data/hora de execução (UTC).
        repeat_interval_minutes: Intervalo de repetição (opcional).
        repeat_until: Data limite para repetição (opcional).
        image_url: URL de imagem opcional.
        video_url: URL de vídeo opcional.
        timezone_str: Fuso horário individual.

    Returns:
        ScheduledNotification: Notificação criada.
    """
    notif = ScheduledNotification(
        tenant_id=tenant_id,
        title=title,
        message_text=message_text,
        run_at=run_at,
        repeat_interval_minutes=repeat_interval_minutes,
        repeat_until=repeat_until,
        image_url=image_url,
        video_url=video_url,
        timezone_str=timezone_str,
        status="PENDING",
    )
    session.add(notif)
    await session.commit()
    await session.refresh(notif)
    logger.info(f"Notificação programada criada: id={notif.id}, run_at={run_at}")
    return notif


async def process_due_notifications(
    session: AsyncSession,
    tenant_id: UUID,
    bot=None,
) -> int:
    """
    Processa notificações programadas vencidas para um tenant.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.
        bot: Instância do Bot (para envio).

    Returns:
        int: Quantidade de notificações processadas.
    """
    now = datetime.now(timezone.utc)

    # Busca notificações PENDING com run_at <= now
    stmt = select(ScheduledNotification).where(
        ScheduledNotification.tenant_id == tenant_id,
        ScheduledNotification.status == "PENDING",
        ScheduledNotification.run_at <= now,
        ScheduledNotification.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    due_notifications = list(result.scalars().all())

    processed = 0
    for notif in due_notifications:
        # Marca como PROCESSING
        notif.status = "PROCESSING"
        notif.last_run_at = now
        await session.commit()

        # Envia para todos os usuários ativos do tenant
        if bot:
            await _send_to_all_users(session, tenant_id, bot, notif)
        else:
            logger.warning(f"Bot não fornecido; notificação {notif.id} não enviada.")

        # Registra a execução no AuditLog
        audit = AuditLog(
            tenant_id=tenant_id,
            action="scheduled_notification.run",
            description=f"Execução da notificação '{notif.title}'",
            actor_user_id=None,
            target_user_id=None,
            metadata_json={"notification_id": str(notif.id)},
        )
        session.add(audit)

        # Se repetir, reagenda
        if notif.repeat_interval_minutes:
            next_run = now + timedelta(minutes=notif.repeat_interval_minutes)
            if notif.repeat_until and next_run > notif.repeat_until:
                notif.status = "COMPLETED"
            else:
                notif.run_at = next_run
                notif.status = "PENDING"
        else:
            notif.status = "COMPLETED"

        await session.commit()
        processed += 1

    logger.info(f"{processed} notificações processadas para tenant {tenant_id}")
    return processed


async def _send_to_all_users(session, tenant_id, bot, notif: ScheduledNotification) -> None:
    """
    Envia a notificação para todos os usuários ativos do tenant.
    """
    from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

    stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.is_blocked == False,
        User.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    users = list(result.scalars().all())

    sent_count = 0
    for user in users:
        try:
            if notif.image_url:
                await bot.send_photo(user.telegram_id, notif.image_url, caption=notif.message_text)
            elif notif.video_url:
                await bot.send_video(user.telegram_id, notif.video_url, caption=notif.message_text)
            else:
                await bot.send_message(user.telegram_id, notif.message_text)
            sent_count += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.warning(f"Falha ao enviar notificação para user_id={user.telegram_id}")
        except Exception as e:
            logger.exception(f"Erro ao enviar notificação: {e}")

    logger.info(f"Notificação {notif.id} enviada para {sent_count} usuários.")
