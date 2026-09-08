"""
Handlers administrativos de Configuração do Mini App.

Seção 28 do painel: gerencia as configurações do Telegram Mini App.
Inclui URL, domínio, nome, logo, tema, produtos, carrinho, recarga,
Pix, histórico, conta bancária, saque, senha, sessão e segurança.
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


class AdminMiniAppStates(StatesGroup):
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


@router.callback_query(F.data == "miniapp_admin:main")
async def miniapp_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração do Mini App."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Valores atuais
        url = await _get_setting(session, tenant.id, "miniapp_url") or "Não configurada"
        domain = await _get_setting(session, tenant.id, "miniapp_domain") or "Não configurado"
        name = await _get_setting(session, tenant.id, "miniapp_name") or "Larizinha Store"
        logo = await _get_setting(session, tenant.id, "miniapp_logo_url") or "Nenhum"
        theme = await _get_setting(session, tenant.id, "miniapp_theme") or "default"
        products_enabled = await _get_setting(session, tenant.id, "miniapp_products_enabled") or "true"
        cart_enabled = await _get_setting(session, tenant.id, "miniapp_cart_enabled") or "true"
        recharge_enabled = await _get_setting(session, tenant.id, "miniapp_recharge_enabled") or "true"
        pix_enabled = await _get_setting(session, tenant.id, "miniapp_pix_enabled") or "true"
        history_enabled = await _get_setting(session, tenant.id, "miniapp_history_enabled") or "true"
        bank_account_enabled = await _get_setting(session, tenant.id, "miniapp_bank_account_enabled") or "true"
        withdrawal_enabled = await _get_setting(session, tenant.id, "miniapp_withdrawal_enabled") or "true"
        password_required = await _get_setting(session, tenant.id, "miniapp_password_required") or "true"
        session_expiration = await _get_setting(session, tenant.id, "miniapp_session_expiration_minutes") or "60"
        webapp_validation = await _get_setting(session, tenant.id, "miniapp_webapp_validation") or "true"

    text = (
        "🧩 CONFIGURAÇÃO DO MINI APP\n\n"
        f"URL: <b>{url}</b>\n"
        f"Domínio: <b>{domain}</b>\n"
        f"Nome: <b>{name}</b>\n"
        f"Logo: <b>{'Configurada' if logo != 'Nenhum' else 'Nenhum'}</b>\n"
        f"Tema: <b>{theme}</b>\n"
        f"Produtos: {'Sim' if products_enabled == 'true' else 'Não'}\n"
        f"Carrinho: {'Sim' if cart_enabled == 'true' else 'Não'}\n"
        f"Recarga: {'Sim' if recharge_enabled == 'true' else 'Não'}\n"
        f"Pix: {'Sim' if pix_enabled == 'true' else 'Não'}\n"
        f"Histórico: {'Sim' if history_enabled == 'true' else 'Não'}\n"
        f"Conta bancária: {'Sim' if bank_account_enabled == 'true' else 'Não'}\n"
        f"Saque: {'Sim' if withdrawal_enabled == 'true' else 'Não'}\n"
        f"Senha obrigatória: {'Sim' if password_required == 'true' else 'Não'}\n"
        f"Expiração de sessão: <b>{session_expiration} min</b>\n"
        f"Validação WebApp: {'Sim' if webapp_validation == 'true' else 'Não'}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("URL", "miniapp_admin:set_url")],
        [create_button("Domínio", "miniapp_admin:set_domain")],
        [create_button("Nome", "miniapp_admin:set_name")],
        [create_button("Logo", "miniapp_admin:set_logo")],
        [create_button("Tema", "miniapp_admin:set_theme")],
        [create_button("Produtos", "miniapp_admin:toggle_products")],
        [create_button("Carrinho", "miniapp_admin:toggle_cart")],
        [create_button("Recarga", "miniapp_admin:toggle_recharge")],
        [create_button("Pix", "miniapp_admin:toggle_pix")],
        [create_button("Histórico", "miniapp_admin:toggle_history")],
        [create_button("Conta bancária", "miniapp_admin:toggle_bank_account")],
        [create_button("Saque", "miniapp_admin:toggle_withdrawal")],
        [create_button("Senha obrigatória", "miniapp_admin:toggle_password")],
        [create_button("Expiração de sessão", "miniapp_admin:set_session_expiration")],
        [create_button("Validação WebApp", "miniapp_admin:toggle_webapp_validation")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


async def _edit_miniapp_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração do Mini App."""
    await state.set_state(AdminMiniAppStates.WAITING_VALUE)
    await state.update_data(miniapp_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "miniapp_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


async def _toggle_miniapp_setting(callback: CallbackQuery, key: str, label: str):
    """Alterna uma configuração booleana do Mini App."""
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
    await miniapp_admin_main(callback, None)


@router.callback_query(F.data == "miniapp_admin:set_url")
async def set_url(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_url", "URL")


@router.callback_query(F.data == "miniapp_admin:set_domain")
async def set_domain(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_domain", "domínio")


@router.callback_query(F.data == "miniapp_admin:set_name")
async def set_name(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_name", "nome")


@router.callback_query(F.data == "miniapp_admin:set_logo")
async def set_logo(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_logo_url", "URL do logo")


@router.callback_query(F.data == "miniapp_admin:set_theme")
async def set_theme(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_theme", "tema")


@router.callback_query(F.data == "miniapp_admin:set_session_expiration")
async def set_session_expiration(callback: CallbackQuery, state: FSMContext):
    await _edit_miniapp_setting(callback, state, "miniapp_session_expiration_minutes", "expiração de sessão (minutos)")


@router.callback_query(F.data == "miniapp_admin:toggle_products")
async def toggle_products(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_products_enabled", "Produtos")


@router.callback_query(F.data == "miniapp_admin:toggle_cart")
async def toggle_cart(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_cart_enabled", "Carrinho")


@router.callback_query(F.data == "miniapp_admin:toggle_recharge")
async def toggle_recharge(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_recharge_enabled", "Recarga")


@router.callback_query(F.data == "miniapp_admin:toggle_pix")
async def toggle_pix(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_pix_enabled", "Pix")


@router.callback_query(F.data == "miniapp_admin:toggle_history")
async def toggle_history(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_history_enabled", "Histórico")


@router.callback_query(F.data == "miniapp_admin:toggle_bank_account")
async def toggle_bank_account(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_bank_account_enabled", "Conta bancária")


@router.callback_query(F.data == "miniapp_admin:toggle_withdrawal")
async def toggle_withdrawal(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_withdrawal_enabled", "Saque")


@router.callback_query(F.data == "miniapp_admin:toggle_password")
async def toggle_password(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_password_required", "Senha obrigatória")


@router.callback_query(F.data == "miniapp_admin:toggle_webapp_validation")
async def toggle_webapp_validation(callback: CallbackQuery, state: FSMContext):
    await _toggle_miniapp_setting(callback, "miniapp_webapp_validation", "Validação WebApp")


@router.message(AdminMiniAppStates.WAITING_VALUE)
async def process_miniapp_setting(message: Message, state: FSMContext):
    """Salva novo valor de configuração do Mini App."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("miniapp_setting_key")

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
    await message.answer("✅ Configuração do Mini App atualizada.")
