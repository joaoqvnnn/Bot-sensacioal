"""
Handlers administrativos de Rankings.

Seção 23 do painel: gerencia configurações dos rankings.
Permite ativar/desativar, escolher tipos, período, quantidade de posições,
privacidade, emojis e medalhas.
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


class AdminRankingsStates(StatesGroup):
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


@router.callback_query(F.data == "rankings_admin:main")
async def rankings_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de rankings."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        rankings_enabled = await _get_setting(session, tenant.id, "rankings_enabled") or "true"
        services_enabled = await _get_setting(session, tenant.id, "rankings_services_enabled") or "true"
        recharges_enabled = await _get_setting(session, tenant.id, "rankings_recharges_enabled") or "true"
        purchases_enabled = await _get_setting(session, tenant.id, "rankings_purchases_enabled") or "true"
        balance_enabled = await _get_setting(session, tenant.id, "rankings_balance_enabled") or "true"
        period = await _get_setting(session, tenant.id, "rankings_period") or "monthly"
        positions = await _get_setting(session, tenant.id, "rankings_positions") or "10"
        privacy = await _get_setting(session, tenant.id, "rankings_privacy") or "username_or_masked"
        medals = await _get_setting(session, tenant.id, "rankings_medals") or "true"

    text = (
        "🏆 CONFIGURAÇÃO DE RANKINGS\n\n"
        f"Status: {'🟢 ON' if rankings_enabled == 'true' else '🔴 OFF'}\n"
        f"Serviços: {'Sim' if services_enabled == 'true' else 'Não'}\n"
        f"Recargas: {'Sim' if recharges_enabled == 'true' else 'Não'}\n"
        f"Compras: {'Sim' if purchases_enabled == 'true' else 'Não'}\n"
        f"Saldo: {'Sim' if balance_enabled == 'true' else 'Não'}\n"
        f"Período: <b>{period}</b>\n"
        f"Posições: <b>{positions}</b>\n"
        f"Privacidade: <b>{privacy}</b>\n"
        f"Medalhas: {'Sim' if medals == 'true' else 'Não'}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar rankings", "rankings_admin:toggle")],
        [create_button("Ranking de serviços", "rankings_admin:toggle_services")],
        [create_button("Ranking de recargas", "rankings_admin:toggle_recharges")],
        [create_button("Ranking de compras", "rankings_admin:toggle_purchases")],
        [create_button("Ranking de saldo", "rankings_admin:toggle_balance")],
        [create_button("Alterar período", "rankings_admin:set_period")],
        [create_button("Alterar posições", "rankings_admin:set_positions")],
        [create_button("Privacidade", "rankings_admin:set_privacy")],
        [create_button("Medalhas", "rankings_admin:toggle_medals")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "rankings_admin:toggle")
async def toggle_rankings(callback: CallbackQuery, state: FSMContext):
    """Alterna status geral dos rankings."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "rankings_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "rankings_enabled", new_val)

    await callback.answer(f"Rankings {'ativados' if new_val == 'true' else 'desativados'}.")
    await rankings_admin_main(callback, state)


async def _toggle_ranking_type(callback: CallbackQuery, key: str, label: str):
    """Alterna um tipo específico de ranking."""
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
    await rankings_admin_main(callback, None)


@router.callback_query(F.data == "rankings_admin:toggle_services")
async def toggle_services(callback: CallbackQuery, state: FSMContext):
    await _toggle_ranking_type(callback, "rankings_services_enabled", "Ranking de serviços")


@router.callback_query(F.data == "rankings_admin:toggle_recharges")
async def toggle_recharges(callback: CallbackQuery, state: FSMContext):
    await _toggle_ranking_type(callback, "rankings_recharges_enabled", "Ranking de recargas")


@router.callback_query(F.data == "rankings_admin:toggle_purchases")
async def toggle_purchases(callback: CallbackQuery, state: FSMContext):
    await _toggle_ranking_type(callback, "rankings_purchases_enabled", "Ranking de compras")


@router.callback_query(F.data == "rankings_admin:toggle_balance")
async def toggle_balance(callback: CallbackQuery, state: FSMContext):
    await _toggle_ranking_type(callback, "rankings_balance_enabled", "Ranking de saldo")


@router.callback_query(F.data == "rankings_admin:toggle_medals")
async def toggle_medals(callback: CallbackQuery, state: FSMContext):
    """Alterna medalhas."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "rankings_medals") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "rankings_medals", new_val)

    await callback.answer(f"Medalhas {'ativadas' if new_val == 'true' else 'desativadas'}.")
    await rankings_admin_main(callback, state)


async def _edit_rankings_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração de ranking."""
    await state.set_state(AdminRankingsStates.WAITING_VALUE)
    await state.update_data(rankings_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "rankings_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "rankings_admin:set_period")
async def set_period(callback: CallbackQuery, state: FSMContext):
    await _edit_rankings_setting(callback, state, "rankings_period", "período (monthly, weekly)")


@router.callback_query(F.data == "rankings_admin:set_positions")
async def set_positions(callback: CallbackQuery, state: FSMContext):
    await _edit_rankings_setting(callback, state, "rankings_positions", "quantidade de posições")


@router.callback_query(F.data == "rankings_admin:set_privacy")
async def set_privacy(callback: CallbackQuery, state: FSMContext):
    await _edit_rankings_setting(callback, state, "rankings_privacy", "privacidade (username_or_masked, id_masked, public_name)")


@router.message(AdminRankingsStates.WAITING_VALUE)
async def process_rankings_setting(message: Message, state: FSMContext):
    """Salva novo valor da configuração de ranking."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("rankings_setting_key")

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
    await message.answer("✅ Configuração de ranking atualizada.")
