"""
Serviço de notificação para canal de compras/estoque.

Após uma compra confirmada, envia mensagem automática para um canal
configurado no painel administrativo (Settings). A mensagem contém
dados públicos/mascarados, sem expor credenciais.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import Bot
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.models.order import Order, OrderItem
from bot.models.user import User
from bot.models.settings import Settings
from bot.core.utils import cents_to_brl

logger = logging.getLogger(__name__)


async def get_channel_id(session, tenant_id: UUID) -> Optional[str]:
    """
    Obtém o ID do canal de compras/estoque configurado para o tenant.

    Args:
        session: Sessão do banco.
        tenant_id: ID do tenant.

    Returns:
        Optional[str]: ID do canal ou None se não configurado.
    """
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == "purchase_channel_id",
        Settings.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def notify_purchase_completed(
    tenant_id: UUID,
    order: Order,
    bot: Bot,
) -> bool:
    """
    Notifica o canal sobre uma compra concluída.

    Args:
        tenant_id: ID do tenant.
        order: Pedido concluído.
        bot: Instância do Bot.

    Returns:
        bool: True se enviado com sucesso, False caso contrário.
    """
    async with get_async_session_factory() as session:
        channel_id = await get_channel_id(session, tenant_id)
        if not channel_id:
            logger.info("Canal de compras não configurado.")
            return False

        # Obtém dados do usuário
        user = (await session.execute(
            select(User).where(User.id == order.user_id)
        )).scalar_one_or_none()
        if user is None:
            logger.error(f"Usuário {order.user_id} não encontrado para pedido {order.id}.")
            return False

        # Obtém primeiro item para nome do produto
        first_item = (await session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id).limit(1)
        )).scalar_one_or_none()
        product_name = first_item.product_name if first_item else "Produto"

        # Monta mensagem (dados mascarados)
        user_display = f"{user.first_name or 'Usuário'} {user.last_name or ''}".strip()
        if not user_display:
            user_display = f"ID: {user.telegram_id}"

        # Mascara ID do Telegram (mostra apenas primeiros 3 e últimos 2)
        tg_id_str = str(user.telegram_id)
        masked_tg = f"{tg_id_str[:3]}***{tg_id_str[-2:]}" if len(tg_id_str) > 5 else tg_id_str

        text = (
            "💎 NOVO ACESSO LIBERADO\n"
            f"👤 Usuário: {user_display} ({masked_tg})\n"
            f"📦 Plano: {product_name}\n"
            f"💵 Status: ✅ Pago e ativo\n"
            f"🕐 Data: {order.created_at.strftime('%d/%m/%Y, %H:%M')}\n"
            "🚀 Acesso liberado automaticamente"
        )

        # Botões configuráveis (futuro via Settings)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🤖 BOT", url="https://t.me/seu_bot"),
                    InlineKeyboardButton(text="📱 CANAL ZAP", url="https://t.me/seu_canal"),
                ]
            ]
        )

        try:
            await bot.send_message(channel_id, text, reply_markup=buttons)
            logger.info(f"Notificação enviada ao canal {channel_id} para pedido {order.id}")
            return True
        except Exception as e:
            logger.exception(f"Erro ao enviar notificação ao canal {channel_id}: {e}")
            return False
