"""
Handlers administrativos de Afiliados.

Seção 16 do painel: configura o sistema de afiliados.
Inclui ON/OFF, percentuais, pontos, saque mínimo, regras de indicação
e visualização de histórico de comissões/pontos.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.settings import Settings
from bot.models.affiliate import AffiliatePoints
from bot.models.referral import AffiliateCommission
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminAffiliatesStates(StatesGroup):
    WAITING_VALUE = State()  # usado para percentual, mínimo, multiplicador, etc.


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


@router.callback_query(F.data == "aff_admin:main")
async def affiliates_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de afiliados."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Valores atuais
        system_enabled = await _get_setting(session, tenant.id, "affiliate_system_enabled") or "true"
        commission_percent = await _get_setting(session, tenant.id, "affiliate_percent") or "20"
        commission_on_purchase = await _get_setting(session, tenant.id, "affiliate_commission_on_purchase") or "false"
        lifetime_commission = await _get_setting(session, tenant.id, "affiliate_lifetime_commission") or "true"
        min_withdrawal = await _get_setting(session, tenant.id, "affiliate_min_withdrawal") or "20.00"
        points_per_recharge = await _get_setting(session, tenant.id, "affiliate_points_per_recharge") or "0"
        min_points_convert = await _get_setting(session, tenant.id, "affiliate_min_points") or "500"
        multiplier = await _get_setting(session, tenant.id, "affiliate_multiplier") or "0.01"

        total_commissions = (await session.execute(
            select(func.sum(AffiliateCommission.amount_cents)).where(
                AffiliateCommission.tenant_id == tenant.id,
                AffiliateCommission.deleted_at.is_(None),
            )
        )).scalar_one() or 0
        total_points = (await session.execute(
            select(func.sum(AffiliatePoints.points)).where(
                AffiliatePoints.tenant_id == tenant.id,
                AffiliatePoints.deleted_at.is_(None),
            )
        )).scalar_one() or 0

    text = (
        "💎 CONFIGURAÇÃO DE AFILIADOS\n\n"
        f"Sistema: {'🟢 ON' if system_enabled == 'true' else '🔴 OFF'}\n"
        f"Comissão sobre recarga: {commission_percent}%\n"
        f"Comissão sobre compra: {'Sim' if commission_on_purchase == 'true' else 'Não'}\n"
        f"Comissão vitalícia: {'Sim' if lifetime_commission == 'true' else 'Não'}\n"
        f"Saque mínimo: R$ {min_withdrawal}\n"
        f"Pontos por recarga: {points_per_recharge}\n"
        f"Pontos mínimos p/ converter: {min_points_convert}\n"
        f"Multiplicador: {multiplier}\n"
        f"Total de comissões: {cents_to_brl(int(total_commissions))}\n"
        f"Total de pontos: {total_points}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar sistema", "aff_admin:toggle_system")],
        [create_button("Alterar comissão (%)", "aff_admin:set_commission")],
        [create_button("Comissão sobre compra", "aff_admin:toggle_purchase_commission")],
        [create_button("Comissão vitalícia", "aff_admin:toggle_lifetime")],
        [create_button("Alterar saque mínimo", "aff_admin:set_min_withdrawal")],
        [create_button("Alterar pontos por recarga", "aff_admin:set_points_per_recharge")],
        [create_button("Alterar pontos mínimos", "aff_admin:set_min_points")],
        [create_button("Alterar multiplicador", "aff_admin:set_multiplier")],
        [create_button("📋 Histórico de comissões", "aff_admin:commission_history")],
        [create_button("📋 Histórico de pontos", "aff_admin:points_history")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# TOGGLES
# ----------------------------------------------------------------------

@router.callback_query(F.data == "aff_admin:toggle_system")
async def toggle_system(callback: CallbackQuery, state: FSMContext):
    """Alterna sistema de afiliados."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "affiliate_system_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "affiliate_system_enabled", new_val)

    await callback.answer(f"Sistema de afiliados {'ativado' if new_val == 'true' else 'desativado'}.")
    await affiliates_admin_main(callback, state)


@router.callback_query(F.data == "aff_admin:toggle_purchase_commission")
async def toggle_purchase_commission(callback: CallbackQuery, state: FSMContext):
    """Alterna comissão sobre compra."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "affiliate_commission_on_purchase") or "false"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "affiliate_commission_on_purchase", new_val)

    await callback.answer(f"Comissão sobre compra {'ativada' if new_val == 'true' else 'desativada'}.")
    await affiliates_admin_main(callback, state)


@router.callback_query(F.data == "aff_admin:toggle_lifetime")
async def toggle_lifetime(callback: CallbackQuery, state: FSMContext):
    """Alterna comissão vitalícia."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "affiliate_lifetime_commission") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "affiliate_lifetime_commission", new_val)

    await callback.answer(f"Comissão vitalícia {'ativada' if new_val == 'true' else 'desativada'}.")
    await affiliates_admin_main(callback, state)


# ----------------------------------------------------------------------
# EDIÇÃO DE VALORES
# ----------------------------------------------------------------------

async def _edit_numeric_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str, is_float: bool = False):
    """Inicia edição de uma configuração numérica."""
    await state.set_state(AdminAffiliatesStates.WAITING_VALUE)
    await state.update_data(setting_key=key, is_float=is_float)
    text = f"Digite o novo valor para {title}:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "aff_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "aff_admin:set_commission")
async def set_commission(callback: CallbackQuery, state: FSMContext):
    await _edit_numeric_setting(callback, state, "affiliate_percent", "comissão (%)")


@router.callback_query(F.data == "aff_admin:set_min_withdrawal")
async def set_min_withdrawal(callback: CallbackQuery, state: FSMContext):
    await _edit_numeric_setting(callback, state, "affiliate_min_withdrawal", "saque mínimo (R$)", is_float=True)


@router.callback_query(F.data == "aff_admin:set_points_per_recharge")
async def set_points_per_recharge(callback: CallbackQuery, state: FSMContext):
    await _edit_numeric_setting(callback, state, "affiliate_points_per_recharge", "pontos por recarga")


@router.callback_query(F.data == "aff_admin:set_min_points")
async def set_min_points(callback: CallbackQuery, state: FSMContext):
    await _edit_numeric_setting(callback, state, "affiliate_min_points", "pontos mínimos para converter")


@router.callback_query(F.data == "aff_admin:set_multiplier")
async def set_multiplier(callback: CallbackQuery, state: FSMContext):
    await _edit_numeric_setting(callback, state, "affiliate_multiplier", "multiplicador", is_float=True)


@router.message(AdminAffiliatesStates.WAITING_VALUE)
async def process_numeric_value(message: Message, state: FSMContext):
    """Recebe e salva o valor da configuração."""
    data = await state.get_data()
    key = data["setting_key"]
    is_float = data.get("is_float", False)
    raw = message.text.strip().replace(",", ".")

    try:
        if is_float:
            value = float(raw)
        else:
            value = int(raw)
    except ValueError:
        await message.answer("Valor inválido.")
        return

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
        await _set_setting(session, tenant.id, key, str(value))

    await state.clear()
    await message.answer("✅ Configuração atualizada.")


# ----------------------------------------------------------------------
# HISTÓRICOS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "aff_admin:commission_history")
async def commission_history(callback: CallbackQuery, state: FSMContext):
    """Exibe últimas comissões geradas."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        commissions = (await session.execute(
            select(AffiliateCommission)
            .where(AffiliateCommission.tenant_id == tenant.id)
            .order_by(AffiliateCommission.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not commissions:
        text = "Nenhuma comissão registrada."
    else:
        text = "💎 Últimas comissões:\n\n"
        for c in commissions:
            text += f"{c.created_at.strftime('%d/%m/%Y %H:%M')} - {cents_to_brl(int(c.amount_cents))} ({c.status})\n"

    buttons = [[create_button("🔙 VOLTAR", "aff_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "aff_admin:points_history")
async def points_history(callback: CallbackQuery, state: FSMContext):
    """Exibe saldo de pontos de usuários."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        points_list = (await session.execute(
            select(User.username, User.first_name, AffiliatePoints.points)
            .join(AffiliatePoints, AffiliatePoints.user_id == User.id)
            .where(AffiliatePoints.tenant_id == tenant.id)
            .order_by(AffiliatePoints.points.desc())
            .limit(10)
        )).all()

    if not points_list:
        text = "Nenhum ponto registrado."
    else:
        text = "🌟 Pontos de afiliados:\n\n"
        for username, first_name, points in points_list:
            display = username or first_name or "Sem nome"
            text += f"{display}: {points} pontos\n"

    buttons = [[create_button("🔙 VOLTAR", "aff_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
