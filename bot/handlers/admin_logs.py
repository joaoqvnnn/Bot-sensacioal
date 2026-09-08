"""
Handlers administrativos de Logs e Auditoria.

Seção 27 do painel: permite visualizar logs de auditoria com filtros
por ação, data e usuário. Não armazena secrets ou senhas.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, desc

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.audit_log import AuditLog
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminLogsStates(StatesGroup):
    WAITING_ACTION = State()
    WAITING_DATE = State()


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
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


async def _is_admin(session, tenant_id: UUID, user_id: UUID) -> bool:
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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "logs_admin:main")
async def logs_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de logs e auditoria."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    text = "📋 LOGS E AUDITORIA\n\nEscolha um filtro:"
    buttons = [
        [create_button("📜 Todos os logs", "logs_admin:view_all")],
        [create_button("🔍 Filtrar por ação", "logs_admin:filter_action")],
        [create_button("🔍 Filtrar por data", "logs_admin:filter_date")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "logs_admin:view_all")
async def view_all_logs(callback: CallbackQuery, state: FSMContext):
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        logs = (await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant.id)
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )).scalars().all()

    if not logs:
        text = "Nenhum log registrado."
    else:
        text = "📜 Últimos 10 logs:\n\n"
        for log in logs:
            text += f"{log.created_at.strftime('%d/%m/%Y %H:%M')} - {log.action} - {log.description or ''}\n"

    buttons = [[create_button("🔙 VOLTAR", "logs_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "logs_admin:filter_action")
async def filter_action_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminLogsStates.WAITING_ACTION)
    text = "Digite a ação que deseja filtrar (ex: wallet.credit, user.block):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "logs_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminLogsStates.WAITING_ACTION)
async def process_filter_action(message: Message, state: FSMContext):
    action = message.text.strip()
    if not action:
        await message.answer("Ação vazia.")
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

        logs = (await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant.id, AuditLog.action == action)
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )).scalars().all()

    if not logs:
        text = "Nenhum log para essa ação."
    else:
        text = f"📜 Logs da ação '{action}':\n\n"
        for log in logs:
            text += f"{log.created_at.strftime('%d/%m/%Y %H:%M')} - {log.description or ''}\n"

    buttons = [[create_button("🔙 VOLTAR", "logs_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()


@router.callback_query(F.data == "logs_admin:filter_date")
async def filter_date_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminLogsStates.WAITING_DATE)
    text = "Digite a data (DD/MM/AAAA) para filtrar:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "logs_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminLogsStates.WAITING_DATE)
async def process_filter_date(message: Message, state: FSMContext):
    try:
        date_str = message.text.strip()
        date_obj = datetime.strptime(date_str, "%d/%m/%Y").date()
        start = datetime(date_obj.year, date_obj.month, date_obj.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
    except ValueError:
        await message.answer("Data inválida.")
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

        logs = (await session.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )).scalars().all()

    if not logs:
        text = "Nenhum log nessa data."
    else:
        text = f"📜 Logs de {date_str}:\n\n"
        for log in logs:
            text += f"{log.created_at.strftime('%H:%M')} - {log.action} - {log.description or ''}\n"

    buttons = [[create_button("🔙 VOLTAR", "logs_admin:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)
    await state.clear()
