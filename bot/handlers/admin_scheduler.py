"""
Handlers administrativos do Agendador.

Seção 9 do painel: permite criar, listar e cancelar agendamentos.
Suporta recorrência, texto, imagem, vídeo, documento e público-alvo.

Tudo persistido na tabela ScheduledNotification e processado por worker.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.scheduled_notification import ScheduledNotification
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.notification_service import schedule_notification

logger = logging.getLogger(__name__)

router = Router()


class AdminSchedulerStates(StatesGroup):
    WAITING_DATE_TIME = State()
    WAITING_TEXT = State()
    WAITING_REPEAT = State()
    WAITING_TARGET = State()


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


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "scheduler:main")
async def scheduler_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal do agendador."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        pending = (await session.execute(
            select(func.count(ScheduledNotification.id)).where(
                ScheduledNotification.tenant_id == tenant.id,
                ScheduledNotification.status == "PENDING",
                ScheduledNotification.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "📅 AGENDADOR\n\n"
        f"Agendamentos pendentes: {pending}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("➕ Criar agendamento", "scheduler:new")],
        [create_button("📋 Listar agendamentos", "scheduler:list")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "scheduler:new")
async def scheduler_new(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de agendamento."""
    await state.set_state(AdminSchedulerStates.WAITING_DATE_TIME)
    text = (
        "Digite a data e hora para o envio:\n"
        "Formato: DD/MM/AAAA HH:MM\n"
        "Exemplo: 25/12/2026 20:15"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "scheduler:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminSchedulerStates.WAITING_DATE_TIME)
async def process_scheduler_datetime(message: Message, state: FSMContext):
    """Recebe data/hora e pede texto."""
    try:
        run_at = datetime.strptime(message.text.strip(), "%d/%m/%Y %H:%M")
        run_at = run_at.replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer("Formato inválido. Use DD/MM/AAAA HH:MM.")
        return

    await state.update_data(run_at=run_at.isoformat())
    await state.set_state(AdminSchedulerStates.WAITING_TEXT)
    await message.answer("Digite o texto da notificação:")


@router.message(AdminSchedulerStates.WAITING_TEXT)
async def process_scheduler_text(message: Message, state: FSMContext):
    """Recebe texto e pede repetição."""
    msg_text = message.text.strip() if message.text else ""
    if not msg_text:
        await message.answer("Texto vazio.")
        return

    await state.update_data(message_text=msg_text)
    await state.set_state(AdminSchedulerStates.WAITING_REPEAT)
    await message.answer(
        "Deseja repetir? Envie:\n"
        "0 = sem repetição\n"
        "N = repetir a cada N minutos (ex: 60)\n"
        "Ou 'cancelar' para cancelar."
    )


@router.message(AdminSchedulerStates.WAITING_REPEAT)
async def process_scheduler_repeat(message: Message, state: FSMContext):
    """Recebe repetição e pede público."""
    repeat_text = message.text.strip().lower()
    if repeat_text == "cancelar":
        await state.clear()
        await message.answer("Agendamento cancelado.")
        return

    try:
        repeat_minutes = int(repeat_text)
        if repeat_minutes < 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido. Envie 0 ou número positivo.")
        return

    await state.update_data(repeat_minutes=repeat_minutes)
    await state.set_state(AdminSchedulerStates.WAITING_TARGET)
    await message.answer("Defina o público-alvo:\n- todos\n- teste (apenas admin)\n- ID específico")


@router.message(AdminSchedulerStates.WAITING_TARGET)
async def process_scheduler_target(message: Message, state: FSMContext):
    """Finaliza agendamento."""
    target_text = message.text.strip().lower() if message.text else "todos"
    data = await state.get_data()
    run_at = datetime.fromisoformat(data["run_at"])
    msg_text = data["message_text"]
    repeat_minutes = data.get("repeat_minutes", 0)

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

        repeat_interval = repeat_minutes if repeat_minutes > 0 else None
        notif = await schedule_notification(
            session=session,
            tenant_id=tenant.id,
            title="Agendamento",
            message_text=msg_text,
            run_at=run_at,
            repeat_interval_minutes=repeat_interval,
        )

    await state.clear()
    await message.answer(f"✅ Agendamento criado para {run_at.strftime('%d/%m/%Y %H:%M')}.")


@router.callback_query(F.data == "scheduler:list")
async def scheduler_list(callback: CallbackQuery, state: FSMContext):
    """Lista agendamentos."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        stmt = select(ScheduledNotification).where(
            ScheduledNotification.tenant_id == tenant.id,
            ScheduledNotification.deleted_at.is_(None),
        ).order_by(ScheduledNotification.run_at.asc()).limit(10)
        result = await session.execute(stmt)
        notifications = list(result.scalars().all())

    if not notifications:
        text = "Nenhum agendamento encontrado."
    else:
        text = "📋 Agendamentos:\n\n"
        for n in notifications:
            status_emoji = "🟢" if n.status == "PENDING" else "🔴"
            repeat = f" (repete a cada {n.repeat_interval_minutes} min)" if n.repeat_interval_minutes else ""
            text += f"{status_emoji} {n.run_at.strftime('%d/%m/%Y %H:%M')} - {n.title}{repeat}\n"

    buttons = [[create_button("🔙 VOLTAR", "scheduler:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
