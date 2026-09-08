"""
Handlers administrativos de WhatsApp.

Seção 20 do painel: gerencia integração com WhatsApp Business API.
Permite configurar número, token, webhook, templates, opt-in,
vinculação Telegram ↔ WhatsApp, mensagens e IA.
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
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminWhatsAppStates(StatesGroup):
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


@router.callback_query(F.data == "whatsapp_admin:main")
async def whatsapp_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração do WhatsApp."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        whatsapp_enabled = await _get_setting(session, tenant.id, "whatsapp_enabled") or "false"
        phone_number_id = await _get_setting(session, tenant.id, "whatsapp_phone_number_id") or "Não configurado"
        business_account_id = await _get_setting(session, tenant.id, "whatsapp_business_account_id") or "Não configurado"
        webhook_verify_token = await _get_setting(session, tenant.id, "whatsapp_webhook_verify_token") or "Não configurado"
        opt_in_required = await _get_setting(session, tenant.id, "whatsapp_opt_in_required") or "true"
        delivery_message_template = await _get_setting(session, tenant.id, "whatsapp_delivery_template") or "Padrão"
        support_ai_enabled = await _get_setting(session, tenant.id, "whatsapp_ai_enabled") or "false"

    text = (
        "📱 CONFIGURAÇÃO WHATSAPP\n\n"
        f"Status: {'🟢 ON' if whatsapp_enabled == 'true' else '🔴 OFF'}\n"
        f"Phone Number ID: <b>{phone_number_id}</b>\n"
        f"Business Account ID: <b>{business_account_id}</b>\n"
        f"Webhook Verify Token: <b>{'Configurado' if webhook_verify_token != 'Não configurado' else 'Não configurado'}</b>\n"
        f"Opt-in obrigatório: <b>{'Sim' if opt_in_required == 'true' else 'Não'}</b>\n"
        f"Template de entrega: <b>{delivery_message_template}</b>\n"
        f"IA no WhatsApp: <b>{'Sim' if support_ai_enabled == 'true' else 'Não'}</b>\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar WhatsApp", "whatsapp_admin:toggle")],
        [create_button("Configurar Phone Number ID", "whatsapp_admin:set_phone_number_id")],
        [create_button("Configurar Business Account ID", "whatsapp_admin:set_business_account_id")],
        [create_button("Configurar Webhook Verify Token", "whatsapp_admin:set_webhook_verify_token")],
        [create_button("Opt-in obrigatório", "whatsapp_admin:toggle_opt_in")],
        [create_button("Template de entrega", "whatsapp_admin:set_delivery_template")],
        [create_button("IA no WhatsApp", "whatsapp_admin:toggle_ai")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "whatsapp_admin:toggle")
async def toggle_whatsapp(callback: CallbackQuery, state: FSMContext):
    """Alterna integração WhatsApp."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "whatsapp_enabled") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "whatsapp_enabled", new_val)

    await callback.answer(f"WhatsApp {'ativado' if new_val == 'true' else 'desativado'}.")
    await whatsapp_admin_main(callback, state)


@router.callback_query(F.data == "whatsapp_admin:toggle_opt_in")
async def toggle_opt_in(callback: CallbackQuery, state: FSMContext):
    """Alterna exigência de opt-in."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "whatsapp_opt_in_required") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "whatsapp_opt_in_required", new_val)

    await callback.answer(f"Opt-in {'obrigatório' if new_val == 'true' else 'opcional'}.")
    await whatsapp_admin_main(callback, state)


@router.callback_query(F.data == "whatsapp_admin:toggle_ai")
async def toggle_ai(callback: CallbackQuery, state: FSMContext):
    """Alterna IA no WhatsApp."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "whatsapp_ai_enabled") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "whatsapp_ai_enabled", new_val)

    await callback.answer(f"IA no WhatsApp {'ativada' if new_val == 'true' else 'desativada'}.")
    await whatsapp_admin_main(callback, state)


async def _edit_whatsapp_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração do WhatsApp."""
    await state.set_state(AdminWhatsAppStates.WAITING_VALUE)
    await state.update_data(whatsapp_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "whatsapp_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "whatsapp_admin:set_phone_number_id")
async def set_phone_number_id(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_phone_number_id", "Phone Number ID")


@router.callback_query(F.data == "whatsapp_admin:set_business_account_id")
async def set_business_account_id(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_business_account_id", "Business Account ID")


@router.callback_query(F.data == "whatsapp_admin:set_webhook_verify_token")
async def set_webhook_verify_token(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_webhook_verify_token", "Webhook Verify Token")


@router.callback_query(F.data == "whatsapp_admin:set_delivery_template")
async def set_delivery_template(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_delivery_template", "Template de entrega")


@router.message(AdminWhatsAppStates.WAITING_VALUE)
async def process_whatsapp_setting(message: Message, state: FSMContext):
    """Salva novo valor da configuração do WhatsApp."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("whatsapp_setting_key")

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
    await message.answer("✅ Configuração do WhatsApp atualizada.")
