"""
Worker de entregas.

Processa DeliveryJob pendentes e realiza o envio pelo método escolhido
(Telegram, WhatsApp, e-mail), registrando tentativas e atualizando status.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from bot.core.database import get_async_session_factory
from bot.integrations.email_sender import EmailSender
from bot.integrations.whatsapp import WhatsAppClient
from bot.models.delivery import DeliveryJob, DeliveryAttempt
from bot.models.user import User
from bot.models.product import Product  # se necessário

logger = logging.getLogger(__name__)


async def send_delivery_task(
    ctx: Dict[str, Any],
    delivery_job_id: str,
) -> bool:
    """
    Processa um job de entrega pendente.

    Args:
        ctx: Contexto do arq.
        delivery_job_id: ID do DeliveryJob (string).

    Returns:
        bool: True se entrega concluída, False caso contrário.
    """
    async with get_async_session_factory() as session:
        # Busca job
        from sqlalchemy import select
        stmt = select(DeliveryJob).where(
            DeliveryJob.id == UUID(delivery_job_id),
            DeliveryJob.deleted_at.is_(None),
        )
        job = (await session.execute(stmt)).scalar_one_or_none()

        if job is None:
            logger.error(f"DeliveryJob {delivery_job_id} não encontrado.")
            return False

        if job.status != "PENDING":
            logger.info(f"DeliveryJob {delivery_job_id} já processado (status={job.status}).")
            return True

        # Marca como PROCESSING
        job.status = "PROCESSING"
        job.last_attempt_at = datetime.now(timezone.utc)
        await session.commit()

        # Determina destinatário
        user = (await session.execute(
            select(User).where(User.id == job.user_id)
        )).scalar_one_or_none()

        if user is None:
            job.status = "FAILED"
            job.error_message = "Usuário não encontrado."
            await session.commit()
            return False

        # Prepara conteúdo (genérico; pode ser melhorado com templates)
        message_text = (
            f"🛍 Sua compra foi aprovada!\n"
            f"🎫 Pedido: {job.order_id}\n"
            f"✅ Status: Pago e ativo\n"
            "Acesse os detalhes no bot ou no e-mail."
        )

        success = False
        error_message = ""

        # Envio conforme método
        try:
            if job.method == "TELEGRAM":
                # Envia mensagem via bot do Telegram (precisa do bot instance)
                # Como o worker não tem o bot diretamente, usaremos um placeholder.
                # Em produção, injetar bot ou usar API HTTP.
                # Por enquanto, registra falha por não implementado.
                error_message = "Envio via Telegram não implementado no worker."
                success = False

            elif job.method == "WHATSAPP":
                whatsapp = WhatsAppClient()
                to_number = user.whatsapp
                if not to_number:
                    error_message = "Usuário sem WhatsApp cadastrado."
                else:
                    # Envia texto; para imagem/botão, adaptar conforme job
                    success = await whatsapp.send_text(to_number, message_text)
                    if not success:
                        error_message = "Falha no envio WhatsApp."

            elif job.method == "EMAIL":
                email_sender = EmailSender()
                to_email = user.email
                if not to_email:
                    error_message = "Usuário sem e-mail cadastrado."
                else:
                    subject = "Sua compra foi aprovada"
                    success = await email_sender.send_email(
                        to=to_email,
                        subject=subject,
                        body=message_text,
                        html=False,
                    )
                    if not success:
                        error_message = "Falha no envio de e-mail."

            else:
                error_message = f"Método de entrega desconhecido: {job.method}"

        except Exception as e:
            logger.exception(f"Erro ao processar entrega {delivery_job_id}: {e}")
            error_message = str(e)
            success = False

        # Registra tentativa
        attempt = DeliveryAttempt(
            tenant_id=job.tenant_id,
            delivery_job_id=job.id,
            status="DELIVERED" if success else "FAILED",
            result_message=error_message or "Entrega realizada.",
            attempted_at=datetime.now(timezone.utc),
        )
        session.add(attempt)

        # Atualiza job
        if success:
            job.status = "DELIVERED"
            job.error_message = None
        else:
            job.status = "FAILED"
            job.error_message = error_message

        await session.commit()
        logger.info(f"DeliveryJob {delivery_job_id} finalizado com status={job.status}")

        return success
