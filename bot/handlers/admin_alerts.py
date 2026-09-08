"""
Handlers administrativos de Alertas de Estoque.

Seção 24 do painel: gerencia configurações dos alertas de estoque.
Permite ativar/desativar, definir produtos disponíveis, mensagem,
imagem, botões, limite de notificações e anti-spam.
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


class AdminAlertsStates(StatesGroup):
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


@router.callback_query(F.data == "alerts_admin:main")
async def alerts_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de alertas de estoque."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        alerts_enabled = await _get_setting(session, tenant.id, "alerts_enabled") or "true"
        available_products = await _get_setting(session, tenant.id, "alerts_available_products") or "all"
        alert_message = await _get_setting(session, tenant.id, "alerts_message") or "🔔 Produto disponível!"
        alert_image = await _get_setting(session, tenant.id, "alerts_image_url") or "Nenhuma"
        alert_buttons = await _get_setting(session, tenant.id, "alerts_buttons") or "[]"
        max_notifications = await _get_setting(session, tenant.id, "alerts_max_notifications") or "3"
        anti_spam = await _get_setting(session, tenant.id, "alerts_anti_spam") or "true"

    text = (
        "⚠️ ALERTAS DE ESTOQUE\n\n"
        f"Status: {'🟢 ON' if alerts_enabled == 'true' else '🔴 OFF'}\n"
        f"Produtos disponíveis: <b>{available_products}</b>\n"
        f"Mensagem: <b>{alert_message[:50]}{'...' if len(alert_message) > 50 else ''}</b>\n"
        f"Imagem: <b>{'Configurada' if alert_image != 'Nenhuma' else 'Nenhuma'}</b>\n"
        f"Botões: <b>{alert_buttons[:50]}</b>\n"
        f"Limite de notificações: <b>{max_notifications}</b>\n"
        f"Anti-spam: <b>{'Sim' if anti_spam == 'true' else 'Não'}</b>\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar alertas", "alerts_admin:toggle")],
        [create_button("Produtos disponíveis", "alerts_admin:set_products")],
        [create_button("Mensagem", "alerts_admin:set_message")],
        [create_button("Imagem", "alerts_admin:set_image")],
        [create_button("Botões", "alerts_admin:set_buttons")],
        [create_button("Limite de notificações", "alerts_admin:set_limit")],
        [create_button("Anti-spam", "alerts_admin:toggle_antispam")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "alerts_admin:toggle")
async def toggle_alerts(callback: CallbackQuery, state: FSMContext):
    """Alterna status dos alertas."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "alerts_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "alerts_enabled", new_val)

    await callback.answer(f"Alertas {'ativados' if new_val == 'true' else 'desativados'}.")
    await alerts_admin_main(callback, state)


@router.callback_query(F.data == "alerts_admin:toggle_antispam")
async def toggle_antispam(callback: CallbackQuery, state: FSMContext):
    """Alterna anti-spam."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "alerts_anti_spam") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "alerts_anti_spam", new_val)

    await callback.answer(f"Anti-spam {'ativado' if new_val == 'true' else 'desativado'}.")
    await alerts_admin_main(callback, state)


async def _edit_alerts_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração de alerta."""
    await state.set_state(AdminAlertsStates.WAITING_VALUE)
    await state.update_data(alerts_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "alerts_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "alerts_admin:set_products")
async def set_products(callback: CallbackQuery, state: FSMContext):
    await _edit_alerts_setting(callback, state, "alerts_available_products", "produtos disponíveis (all ou lista de IDs)")


@router.callback_query(F.data == "alerts_admin:set_message")
async def set_message(callback: CallbackQuery, state: FSMContext):
    await _edit_alerts_setting(callback, state, "alerts_message", "mensagem do alerta")


@router.callback_query(F.data == "alerts_admin:set_image")
async def set_image(callback: CallbackQuery, state: FSMContext):
    await _edit_alerts_setting(callback, state, "alerts_image_url", "URL da imagem")


@router.callback_query(F.data == "alerts_admin:set_buttons")
async def set_buttons(callback: CallbackQuery, state: FSMContext):
    await _edit_alerts_setting(callback, state, "alerts_buttons", "botões (JSON)")


@router.callback_query(F.data == "alerts_admin:set_limit")
async def set_limit(callback: CallbackQuery, state: FSMContext):
    await _edit_alerts_setting(callback, state, "alerts_max_notifications", "limite de notificações")


@router.message(AdminAlertsStates.WAITING_VALUE)
async def process_alerts_setting(message: Message, state: FSMContext):
    """Salva novo valor da configuração de alerta."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("alerts_setting_key")

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
    await message.answer("✅ Configuração de alerta atualizada.")
