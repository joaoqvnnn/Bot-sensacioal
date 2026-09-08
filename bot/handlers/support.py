"""
Handler de suporte (IA + humano).

Fluxo:
- Usuário clica em "🎧 ATENDIMENTO" no menu principal
- O bot mostra tela de suporte e aguarda dúvida (FSM)
- A IA responde usando OpenAIClient
- Se o usuário digitar "humano" ou "falar com atendente", cria ticket
  e encerra o atendimento automático (futuro: notificar admin)
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.integrations.openai_client import OpenAIClient
from bot.keyboards.utils import create_button
from bot.models.support import SupportTicket, SupportMessage
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class SupportStates(StatesGroup):
    WAITING_QUESTION = State()


async def _get_tenant_and_user(message_or_callback):
    """Obtém tenant e usuário a partir de Message ou Callback."""
    bot = message_or_callback.bot
    user_id = message_or_callback.from_user.id
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=user_id,
            username=message_or_callback.from_user.username,
            first_name=message_or_callback.from_user.first_name,
            last_name=message_or_callback.from_user.last_name,
        )
        return tenant, user


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


async def _get_ai_response(user_message: str) -> Optional[str]:
    """
    Usa IA para responder dúvida, com prompt limitado ao sistema.
    """
    client = OpenAIClient()
    # Mensagens de sistema para contexto
    system_prompt = (
        "Você é o suporte da Larizinha Store. Responda de forma clara e objetiva "
        "somente sobre assuntos permitidos: produtos, compras, pagamentos, saldo, "
        "entregas, prazos, garantia, etc. Não invente informações. Se não souber, "
        "diga para o usuário aguardar atendimento humano."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    response = await client.chat_completion(messages, temperature=0.5, max_tokens=300)
    return response


@router.callback_query(F.data == "menu:support")
async def show_support_menu(callback: CallbackQuery, state: FSMContext):
    """Inicia o atendimento."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    text = (
        "🎧 ATENDIMENTO\n\n"
        "Olá! Eu sou o assistente virtual da Larizinha Store.\n"
        "Pode me perguntar sobre produtos, compras, pagamentos, etc.\n"
        "Digite sua dúvida abaixo.\n"
        "Se preferir falar com um humano, digite 'humano'."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 VOLTAR", "menu:back")]]
    )
    await _edit_or_answer(callback, text, keyboard)

    # Define estado para aguardar a pergunta
    await state.set_state(SupportStates.WAITING_QUESTION)


@router.message(SupportStates.WAITING_QUESTION)
async def process_support_question(message: Message, state: FSMContext):
    """Processa a pergunta do usuário, responde com IA ou transfere."""
    user_text = message.text.strip() if message.text else ""

    # Se usuário digitar humano, criar ticket e encerrar IA
    if user_text.lower() in ["humano", "falar com atendente", "atendente", "suporte humano"]:
        await _transfer_to_human(message, state)
        return

    # Responde com IA
    ai_response = await _get_ai_response(user_text)
    if ai_response:
        await message.answer(ai_response)
    else:
        await message.answer(
            "Desculpe, não consegui processar sua solicitação.\n"
            "Digite 'humano' para falar com um atendente."
        )
    # Mantém estado para continuar conversa
    # (não limpa estado)


async def _transfer_to_human(message: Message, state: FSMContext):
    """
    Cria ticket de suporte e encerra atendimento automático.
    Futuramente notificará admin responsável.
    """
    tenant, user = await _get_tenant_and_user(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        # Cria ticket
        ticket = SupportTicket(
            tenant_id=tenant.id,
            user_id=user.id,
            status="OPEN",
            subject="Atendimento humano solicitado",
            is_ai_handling=False,
        )
        session.add(ticket)
        await session.flush()

        # Registra mensagem do usuário (a última)
        if message.text:
            msg = SupportMessage(
                tenant_id=tenant.id,
                ticket_id=ticket.id,
                sender_type="USER",
                content=message.text,
            )
            session.add(msg)

        await session.commit()

    await message.answer(
        "✅ Sua solicitação foi encaminhada para um atendente humano.\n"
        "Em breve alguém entrará em contato. Obrigado pela paciência!"
    )
    await state.clear()
