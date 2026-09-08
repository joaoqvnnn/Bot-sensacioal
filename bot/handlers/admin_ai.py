"""
Handlers administrativos de IA.

Seção 21 do painel: gerencia configurações da IA.
Permite ativar/desativar, definir modelo, limites de tokens/mensagens,
escopo de atuação, transferência para humano, rate limit e bloqueio.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminAIStates(StatesGroup):
    WAITING_VALUE = State()


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
    """Obtém tenant e usuário a partir do callback."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, callback.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        return tenant, user


async def _get_tenant_and_user_from_message(message: Message):
    """Obtém tenant e usuário a partir de mensagem."""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            return None, None
        user = await get_or_create_user(
            session=session,
            tenant=tenant,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        return tenant, user


async def _is_admin(session, tenant_id: UUID, user_id: UUID) -> bool:
    """Verifica se o usuário é administrador ou dono no tenant."""
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True

    from bot.models.admin_user import AdminUser
    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
            AdminUser.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return admin is not None


async def _get_setting(session, tenant_id: UUID, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(session, tenant_id: UUID, key: str, value: str) -> None:
    """Cria ou atualiza configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = Settings(tenant_id=tenant_id, key=key, value=value)
        session.add(setting)
    await session.commit()


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "ai_admin:main")
async def ai_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração da IA."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        ai_enabled = await _get_setting(session, tenant.id, "ai_enabled") or "false"
        model = await _get_setting(session, tenant.id, "ai_model") or settings.OPENAI_MODEL or "gpt-4o-mini"
        max_tokens = await _get_setting(session, tenant.id, "ai_max_tokens") or "500"
        max_messages = await _get_setting(session, tenant.id, "ai_max_messages_per_user") or "20"
        scope_products = await _get_setting(session, tenant.id, "ai_scope_products") or "true"
        scope_orders = await _get_setting(session, tenant.id, "ai_scope_orders") or "true"
        scope_support = await _get_setting(session, tenant.id, "ai_scope_support") or "true"
        transfer_to_human = await _get_setting(session, tenant.id, "ai_transfer_to_human") or "true"
        rate_limit = await _get_setting(session, tenant.id, "ai_rate_limit_per_minute") or "5"

    text = (
        "🤖 CONFIGURAÇÃO DE IA\n\n"
        f"Status: {'🟢 ON' if ai_enabled == 'true' else '🔴 OFF'}\n"
        f"Modelo: <b>{model}</b>\n"
        f"Limite de tokens: <b>{max_tokens}</b>\n"
        f"Limite de mensagens por usuário: <b>{max_messages}</b>\n"
        f"Escopo produtos: <b>{'Sim' if scope_products == 'true' else 'Não'}</b>\n"
        f"Escopo pedidos: <b>{'Sim' if scope_orders == 'true' else 'Não'}</b>\n"
        f"Escopo suporte: <b>{'Sim' if scope_support == 'true' else 'Não'}</b>\n"
        f"Transferência para humano: <b>{'Sim' if transfer_to_human == 'true' else 'Não'}</b>\n"
        f"Rate limit por minuto: <b>{rate_limit}</b>\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar IA", "ai_admin:toggle")],
        [create_button("Alterar modelo", "ai_admin:set_model")],
        [create_button("Alterar limite de tokens", "ai_admin:set_max_tokens")],
        [create_button("Alterar limite de mensagens", "ai_admin:set_max_messages")],
        [create_button("Escopo produtos", "ai_admin:toggle_scope_products")],
        [create_button("Escopo pedidos", "ai_admin:toggle_scope_orders")],
        [create_button("Escopo suporte", "ai_admin:toggle_scope_support")],
        [create_button("Transferência para humano", "ai_admin:toggle_transfer")],
        [create_button("Alterar rate limit", "ai_admin:set_rate_limit")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "ai_admin:toggle")
async def toggle_ai(callback: CallbackQuery, state: FSMContext):
    """Alterna status da IA."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "ai_enabled") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "ai_enabled", new_val)

    await callback.answer(f"IA {'ativada' if new_val == 'true' else 'desativada'}.")
    await ai_admin_main(callback, state)


async def _toggle_scope(callback: CallbackQuery, key: str, label: str):
    """Alterna um escopo específico."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, key) or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, key, new_val)

    await callback.answer(f"{label} {'ativado' if new_val == 'true' else 'desativado'}.")
    await ai_admin_main(callback, None)


@router.callback_query(F.data == "ai_admin:toggle_scope_products")
async def toggle_scope_products(callback: CallbackQuery, state: FSMContext):
    await _toggle_scope(callback, "ai_scope_products", "Escopo produtos")


@router.callback_query(F.data == "ai_admin:toggle_scope_orders")
async def toggle_scope_orders(callback: CallbackQuery, state: FSMContext):
    await _toggle_scope(callback, "ai_scope_orders", "Escopo pedidos")


@router.callback_query(F.data == "ai_admin:toggle_scope_support")
async def toggle_scope_support(callback: CallbackQuery, state: FSMContext):
    await _toggle_scope(callback, "ai_scope_support", "Escopo suporte")


@router.callback_query(F.data == "ai_admin:toggle_transfer")
async def toggle_transfer(callback: CallbackQuery, state: FSMContext):
    await _toggle_scope(callback, "ai_transfer_to_human", "Transferência para humano")


async def _edit_ai_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração da IA."""
    await state.set_state(AdminAIStates.WAITING_VALUE)
    await state.update_data(ai_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "ai_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "ai_admin:set_model")
async def set_model(callback: CallbackQuery, state: FSMContext):
    await _edit_ai_setting(callback, state, "ai_model", "modelo")


@router.callback_query(F.data == "ai_admin:set_max_tokens")
async def set_max_tokens(callback: CallbackQuery, state: FSMContext):
    await _edit_ai_setting(callback, state, "ai_max_tokens", "limite de tokens")


@router.callback_query(F.data == "ai_admin:set_max_messages")
async def set_max_messages(callback: CallbackQuery, state: FSMContext):
    await _edit_ai_setting(callback, state, "ai_max_messages_per_user", "limite de mensagens por usuário")


@router.callback_query(F.data == "ai_admin:set_rate_limit")
async def set_rate_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_ai_setting(callback, state, "ai_rate_limit_per_minute", "rate limit por minuto")


@router.message(AdminAIStates.WAITING_VALUE)
async def process_ai_setting(message: Message, state: FSMContext):
    """Salva novo valor da configuração da IA."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("ai_setting_key")

    tenant, admin = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, setting_key, new_value)

    await state.clear()
    await message.answer("✅ Configuração de IA atualizada.")
