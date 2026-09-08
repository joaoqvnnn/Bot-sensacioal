"""
Handler do comando /start e navegação inicial.

Fluxo:
1. Verifica se o usuário está inscrito no canal obrigatório.
2. Se não estiver, exibe mensagem de bloqueio com botão para entrar no canal.
3. Se estiver, exibe a tela principal com os botões de navegação.
"""

import logging
import json
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.keyboards.main import get_main_keyboard
from bot.services.user_service import (
    get_or_create_user,
    check_channel_membership,
    get_tenant_for_bot,
)
from bot.models.tenant import Tenant

logger = logging.getLogger(__name__)

router = Router()


async def _get_tenant(bot_username: str):
    """Obtém o tenant associado ao bot."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, bot_username)
        return tenant


async def _send_main_menu(message: Message, user, tenant):
    """
    Envia a tela principal do usuário.
    """
    # Texto padrão da home (futuramente virá do banco)
    text = (
        f"🎬 Bem-vindo à <b>{settings.APP_NAME}</b>! ✨\n"
        "A sua central de streamings com entrega 100% automática.\n"
        "Pagou, recebeu. Sem filas, sem precisar falar com atendente, 24 horas por dia! ⚡️\n\n"
        "🛡 Segurança e Suporte:\n"
        "Mais de 12.000 clientes já passaram por aqui.\n"
        "Participe da nossa comunidade e veja as referências\n\n"
        "💠 Seus Dados:\n"
        f"├👤 ID: {user.telegram_id}\n"
        f"└💰 Saldo Atual: R$ 0,00\n\n"
        "👇 COMO COMEÇAR:\n"
        "Clique no botão \"🛍 Comprar Produtos\" abaixo para ver nosso catálogo e escolher sua tela!"
    )
    keyboard = get_main_keyboard()
    await message.answer(text, reply_markup=keyboard)


async def _send_channel_required(message: Message, tenant: Tenant):
    """
    Exibe mensagem pedindo para entrar no canal obrigatório.
    """
    # Canal configurado no settings_json do tenant (ou fallback global)
    channel_link = None
    if tenant.settings_json:
        try:
            tenant_settings = json.loads(tenant.settings_json)
            channel_link = tenant_settings.get("mandatory_channel_link")
        except Exception:
            channel_link = None

    if not channel_link:
        channel_link = str(settings.SUPPORT_CHAT_LINK) if settings.SUPPORT_CHAT_LINK else "https://t.me/"

    text = (
        "❗️ Para utilizar nosso serviço é obrigatório que você entre no nosso grupo.\n"
        "➡️ ENTRE NO CANAL"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                {
                    "text": "➡️ ENTRE NO CANAL",
                    "url": channel_link,
                }
            ]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """
    Manipula o comando /start.
    """
    # Limpa qualquer estado anterior
    await state.clear()

    # Obtém o tenant usando o username configurado
    tenant = await _get_tenant(settings.TELEGRAM_BOT_USERNAME)
    if tenant is None:
        logger.error("Nenhum tenant ativo encontrado.")
        await message.answer("⚠️ Sistema indisponível. Tente novamente mais tarde.")
        return

    # Obtém ou cria usuário
    async with get_async_session_factory() as session:
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        # Verifica bloqueio
        if user.is_blocked:
            await message.answer("🚫 Você está bloqueado. Contate o suporte.")
            return

        # Verifica assinatura do canal
        is_member = await check_channel_membership(
            bot=bot,
            tenant=tenant,
            telegram_id=message.from_user.id,
        )

        if not is_member:
            await _send_channel_required(message, tenant)
        else:
            await _send_main_menu(message, user, tenant)


@router.callback_query(F.data == "menu:back")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """
    Retorna para a tela principal a partir de qualquer callback "menu:back".
    """
    if callback.message:
        await callback.answer()
        user_telegram_id = callback.from_user.id

        async with get_async_session_factory() as session:
            tenant = await get_tenant_for_bot(session, settings.TELEGRAM_BOT_USERNAME)
            if tenant:
                user = await get_or_create_user(
                    session=session,
                    tenant=tenant,
                    telegram_id=user_telegram_id,
                    username=callback.from_user.username,
                    first_name=callback.from_user.first_name,
                    last_name=callback.from_user.last_name,
                )

                text = (
                    f"🎬 Bem-vindo à <b>{settings.APP_NAME}</b>! ✨\n"
                    "A sua central de streamings com entrega 100% automática.\n"
                    "Pagou, recebeu. Sem filas, sem precisar falar com atendente, 24 horas por dia! ⚡️\n\n"
                    "💠 Seus Dados:\n"
                    f"├👤 ID: {user.telegram_id}\n"
                    f"└💰 Saldo Atual: R$ 0,00\n\n"
                    "👇 COMO COMEÇAR:\n"
                    "Clique no botão \"🛍 Comprar Produtos\" abaixo para ver nosso catálogo!"
                )
                await callback.message.edit_text(text, reply_markup=get_main_keyboard())
            else:
                await callback.message.edit_text("⚠️ Sistema indisponível.")
