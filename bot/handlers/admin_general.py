"""
Handlers administrativos de Configurações Gerais.

Permite ao administrador visualizar e editar as configurações gerais do bot,
como nome, imagem, fuso, links, canais, logs, separador, manutenção, etc.
Todas as alterações são persistidas na tabela Settings e controlam o sistema real.
"""

import logging
from datetime import datetime, timezone
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
from bot.models.tenant import Tenant
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class GeneralSettingsStates(StatesGroup):
    WAITING_VALUE = State()  # usado para capturar texto simples


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
    """Busca valor de configuração por chave."""
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
# MENU PRINCIPAL DE CONFIGURAÇÕES GERAIS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admin:general")
async def show_general_settings(callback: CallbackQuery, state: FSMContext):
    """Exibe o menu de Configurações Gerais com os valores atuais."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Coleta valores atuais (com fallback para .env/defaults)
        bot_name = await _get_setting(session, tenant.id, "bot_name") or settings.APP_NAME
        bot_username = callback.bot.username
        bot_image = await _get_setting(session, tenant.id, "bot_image_url") or "Não definida"
        store_name = await _get_setting(session, tenant.id, "store_name") or bot_name
        timezone = await _get_setting(session, tenant.id, "timezone") or settings.TIMEZONE
        language = await _get_setting(session, tenant.id, "language") or "pt-BR"
        currency = await _get_setting(session, tenant.id, "currency") or "BRL"
        support_link = await _get_setting(session, tenant.id, "support_link") or str(settings.SUPPORT_CHAT_LINK or "")
        mandatory_channel_link = await _get_setting(session, tenant.id, "mandatory_channel_link") or "Não definido"
        mandatory_channel_id = await _get_setting(session, tenant.id, "mandatory_channel_id") or "Não definido"
        purchase_channel_id = await _get_setting(session, tenant.id, "purchase_channel_id") or "Não definido"
        log_channel_id = await _get_setting(session, tenant.id, "log_channel_id") or "Não definido"
        separator = await _get_setting(session, tenant.id, "separator") or "==="
        maintenance_mode = await _get_setting(session, tenant.id, "maintenance_mode") or "false"
        maintenance_message = await _get_setting(session, tenant.id, "maintenance_message") or "🔧 BOT EM MANUTENÇÃO"
        maintenance_return_message = await _get_setting(session, tenant.id, "maintenance_return_message") or "🟢 BOT ONLINE"
        vip_status = tenant.vip
        expires_at = tenant.expires_at.strftime("%d/%m/%Y") if tenant.expires_at else "Sem vencimento"

    text = (
        "🏠 CONFIGURAÇÕES GERAIS\n\n"
        f"🤖 Nome do bot: <b>{bot_name}</b>\n"
        f"📛 Username: @{bot_username}\n"
        f"🖼️ Foto principal: <b>{bot_image}</b>\n"
        f"🏪 Nome da loja: <b>{store_name}</b>\n"
        f"🕒 Fuso horário: <b>{timezone}</b>\n"
        f"🌐 Idioma: <b>{language}</b>\n"
        f"💰 Moeda: <b>{currency}</b>\n"
        f"🔗 Link suporte: <b>{support_link}</b>\n"
        f"🔗 Link canal obrigatório: <b>{mandatory_channel_link}</b>\n"
        f"🆔 ID canal obrigatório: <b>{mandatory_channel_id}</b>\n"
        f"🛒 ID canal compras/estoque: <b>{purchase_channel_id}</b>\n"
        f"📋 ID canal logs: <b>{log_channel_id}</b>\n"
        f"✂️ Separador: <b>{separator}</b>\n"
        f"🔧 Manutenção: <b>{'🟢 ON' if maintenance_mode == 'true' else '🔴 OFF'}</b>\n"
        f"💬 Msg manutenção: <b>{maintenance_message[:30]}...</b>\n"
        f"💬 Msg retorno: <b>{maintenance_return_message[:30]}...</b>\n"
        f"👑 VIP: <b>{'Sim' if vip_status else 'Não'}</b>\n"
        f"📅 Vencimento: <b>{expires_at}</b>\n"
        f"🔁 Versão: <b>{settings.APP_NAME} v{settings.APP_ENV}</b>\n"
        "\nSelecione um item para editar:"
    )

    # Organiza botões por categoria
    buttons = [
        [create_button("🤖 Nome do bot", "general:edit:bot_name")],
        [create_button("🖼️ Foto principal", "general:edit:bot_image")],
        [create_button("🏪 Nome da loja", "general:edit:store_name")],
        [create_button("🕒 Fuso horário", "general:edit:timezone")],
        [create_button("🌐 Idioma", "general:edit:language")],
        [create_button("💰 Moeda", "general:edit:currency")],
        [create_button("🔗 Link suporte", "general:edit:support_link")],
        [create_button("🔗 Link canal obrigatório", "general:edit:mandatory_channel_link")],
        [create_button("🆔 ID canal obrigatório", "general:edit:mandatory_channel_id")],
        [create_button("🛒 ID canal compras", "general:edit:purchase_channel_id")],
        [create_button("📋 ID canal logs", "general:edit:log_channel_id")],
        [create_button("✂️ Separador", "general:edit:separator")],
        [create_button("🔧 Alternar manutenção", "general:toggle:maintenance")],
        [create_button("💬 Msg manutenção", "general:edit:maintenance_message")],
        [create_button("💬 Msg retorno manutenção", "general:edit:maintenance_return_message")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# HANDLERS DE EDIÇÃO GENÉRICA (callback: general:edit:<chave>)
# ----------------------------------------------------------------------

@router.callback_query(F.data.startswith("general:edit:"))
async def edit_generic_setting(callback: CallbackQuery, state: FSMContext):
    """Inicia a edição de uma configuração genérica."""
    key = callback.data.split(":", 2)[2]  # "general:edit:bot_name" -> "bot_name"

    # Mapeia chave para título amigável
    titles = {
        "bot_name": "Nome do bot",
        "bot_image": "URL da foto principal",
        "store_name": "Nome da loja",
        "timezone": "Fuso horário (ex: America/Sao_Paulo)",
        "language": "Idioma (ex: pt-BR)",
        "currency": "Moeda (ex: BRL)",
        "support_link": "Link de suporte",
        "mandatory_channel_link": "Link do canal obrigatório",
        "mandatory_channel_id": "ID do canal obrigatório",
        "purchase_channel_id": "ID do canal de compras/estoque",
        "log_channel_id": "ID do canal de logs",
        "separator": "Separador de comandos/importações",
        "maintenance_message": "Mensagem de manutenção",
        "maintenance_return_message": "Mensagem de retorno da manutenção",
    }
    title = titles.get(key, key.replace("_", " ").title())

    await state.set_state(GeneralSettingsStates.WAITING_VALUE)
    await state.update_data(setting_key=key)

    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:general")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(GeneralSettingsStates.WAITING_VALUE)
async def process_generic_value(message: Message, state: FSMContext):
    """Salva o valor digitado para a configuração."""
    new_value = message.text.strip() if message.text else ""
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("setting_key")

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, setting_key, new_value)

    await state.clear()
    await message.answer("✅ Configuração atualizada com sucesso!")


# ----------------------------------------------------------------------
# TOGGLE DE MANUTENÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "general:toggle:maintenance")
async def toggle_maintenance(callback: CallbackQuery, state: FSMContext):
    """Alterna o modo manutenção."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "maintenance_mode") or "false"
        new_value = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "maintenance_mode", new_value)

    await callback.answer(f"Modo manutenção {'ativado' if new_value == 'true' else 'desativado'}.")
    await show_general_settings(callback, state)
