"""
Handlers administrativos de WhatsApp.

Seção 20 do painel: gerencia integração com WhatsApp Business API.
Inclui configuração de número, token, webhook, templates, opt-in,
vinculação Telegram ↔ WhatsApp, mensagem de compra, imagem do produto,
botão ATIVAR, WhatsApp Flow, status de entrega, retry, histórico, IA,
limites e segurança.
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
    WAITING_TEMPLATE_TEXT = State()
    WAITING_TEMPLATE_BUTTON = State()


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


# ----------------------------------------------------------------------
# MENU PRINCIPAL
# ----------------------------------------------------------------------

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
        delivery_template = await _get_setting(session, tenant.id, "whatsapp_delivery_template") or "Padrão"
        ai_enabled = await _get_setting(session, tenant.id, "whatsapp_ai_enabled") or "false"
        link_enabled = await _get_setting(session, tenant.id, "whatsapp_link_enabled") or "true"
        retry_count = await _get_setting(session, tenant.id, "whatsapp_retry_count") or "3"
        rate_limit = await _get_setting(session, tenant.id, "whatsapp_rate_limit_per_minute") or "10"

    text = (
        "📱 CONFIGURAÇÃO WHATSAPP\n\n"
        f"Status: {'🟢 ON' if whatsapp_enabled == 'true' else '🔴 OFF'}\n"
        f"Phone Number ID: <b>{phone_number_id}</b>\n"
        f"Business Account ID: <b>{business_account_id}</b>\n"
        f"Webhook Verify Token: <b>{'Configurado' if webhook_verify_token != 'Não configurado' else 'Não configurado'}</b>\n"
        f"Opt-in obrigatório: <b>{'Sim' if opt_in_required == 'true' else 'Não'}</b>\n"
        f"Template de entrega: <b>{delivery_template}</b>\n"
        f"IA no WhatsApp: <b>{'Sim' if ai_enabled == 'true' else 'Não'}</b>\n"
        f"Vincular Telegram ↔ WhatsApp: <b>{'Sim' if link_enabled == 'true' else 'Não'}</b>\n"
        f"Retry: <b>{retry_count}</b>\n"
        f"Rate limit por minuto: <b>{rate_limit}</b>\n\n"
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
        [create_button("Vincular Telegram ↔ WhatsApp", "whatsapp_admin:toggle_link")],
        [create_button("Retry", "whatsapp_admin:set_retry")],
        [create_button("Rate limit", "whatsapp_admin:set_rate_limit")],
        [create_button("Mensagens e Templates", "whatsapp_admin:messages_menu")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# TOGGLES
# ----------------------------------------------------------------------

async def _toggle_setting(callback: CallbackQuery, state: FSMContext, key: str, label: str):
    """Alterna uma configuração booleana."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, key) or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, key, new_val)

    await callback.answer(f"{label} {'ativado' if new_val == 'true' else 'desativado'}.")
    await whatsapp_admin_main(callback, state)


@router.callback_query(F.data == "whatsapp_admin:toggle")
async def toggle_whatsapp(callback: CallbackQuery, state: FSMContext):
    await _toggle_setting(callback, state, "whatsapp_enabled", "WhatsApp")


@router.callback_query(F.data == "whatsapp_admin:toggle_opt_in")
async def toggle_opt_in(callback: CallbackQuery, state: FSMContext):
    await _toggle_setting(callback, state, "whatsapp_opt_in_required", "Opt-in")


@router.callback_query(F.data == "whatsapp_admin:toggle_ai")
async def toggle_ai(callback: CallbackQuery, state: FSMContext):
    await _toggle_setting(callback, state, "whatsapp_ai_enabled", "IA")


@router.callback_query(F.data == "whatsapp_admin:toggle_link")
async def toggle_link(callback: CallbackQuery, state: FSMContext):
    await _toggle_setting(callback, state, "whatsapp_link_enabled", "Vinculação Telegram ↔ WhatsApp")


# ----------------------------------------------------------------------
# EDIÇÃO DE VALORES
# ----------------------------------------------------------------------

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


@router.callback_query(F.data == "whatsapp_admin:set_retry")
async def set_retry(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_retry_count", "Número de retry")


@router.callback_query(F.data == "whatsapp_admin:set_rate_limit")
async def set_rate_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_whatsapp_setting(callback, state, "whatsapp_rate_limit_per_minute", "Rate limit por minuto")


@router.message(AdminWhatsAppStates.WAITING_VALUE)
async def process_whatsapp_setting(message: Message, state: FSMContext):
    """Salva novo valor de configuração do WhatsApp."""
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


# ----------------------------------------------------------------------
# MENSAGENS E TEMPLATES
# ----------------------------------------------------------------------

WHATSAPP_TEMPLATE_TYPES = {
    "purchase": "Mensagem de compra",
    "delivery": "Mensagem de entrega",
    "image": "Imagem do produto",
    "button": "Botão ATIVAR",
    "flow": "WhatsApp Flow",
    "link": "Mensagem de vinculação Telegram ↔ WhatsApp",
}


@router.callback_query(F.data == "whatsapp_admin:messages_menu")
async def messages_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de mensagens e templates do WhatsApp."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    text = "💬 Mensagens/Templates do WhatsApp\n\nSelecione:"
    buttons = []
    for code, label in WHATSAPP_TEMPLATE_TYPES.items():
        buttons.append([create_button(label, f"whatsapp_admin:template_edit:{code}")])
    buttons.append([create_button("🔙 VOLTAR", "whatsapp_admin:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("whatsapp_admin:template_edit:"))
async def template_edit(callback: CallbackQuery, state: FSMContext):
    """Inicia edição de um template/mensagem."""
    template_code = callback.data.split(":")[-1]
    template_label = WHATSAPP_TEMPLATE_TYPES.get(template_code, template_code)

    await state.update_data(whatsapp_template_code=template_code)

    if template_code in ("purchase", "delivery", "link"):
        await state.set_state(AdminWhatsAppStates.WAITING_TEMPLATE_TEXT)
        text = f"Digite o texto para <b>{template_label}</b>:"
    elif template_code == "image":
        await state.set_state(AdminWhatsAppStates.WAITING_TEMPLATE_TEXT)
        text = "Digite a URL da imagem do produto para a mensagem WhatsApp:"
    elif template_code == "button":
        await state.set_state(AdminWhatsAppStates.WAITING_TEMPLATE_BUTTON)
        text = "Digite o texto do botão ATIVAR (ex: 🔐 ATIVAR):"
    elif template_code == "flow":
        await state.set_state(AdminWhatsAppStates.WAITING_TEMPLATE_TEXT)
        text = "Digite o ID ou nome do WhatsApp Flow:"
    else:
        await callback.answer("Tipo não suportado.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "whatsapp_admin:messages_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminWhatsAppStates.WAITING_TEMPLATE_TEXT)
async def process_template_text(message: Message, state: FSMContext):
    """Salva texto do template/mensagem."""
    value = message.text.strip()
    if not value:
        await message.answer("Valor vazio.")
        return

    data = await state.get_data()
    template_code = data.get("whatsapp_template_code")

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
        await _set_setting(session, tenant.id, f"whatsapp_{template_code}_text", value)

    await state.clear()
    await message.answer("✅ Mensagem/Template atualizado.")


@router.message(AdminWhatsAppStates.WAITING_TEMPLATE_BUTTON)
async def process_template_button(message: Message, state: FSMContext):
    """Salva texto do botão ATIVAR."""
    value = message.text.strip()
    if not value:
        await message.answer("Valor vazio.")
        return

    data = await state.get_data()
    template_code = data.get("whatsapp_template_code")  # "button"

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
        await _set_setting(session, tenant.id, f"whatsapp_{template_code}_text", value)

    await state.clear()
    await message.answer("✅ Botão ATIVAR atualizado.")
