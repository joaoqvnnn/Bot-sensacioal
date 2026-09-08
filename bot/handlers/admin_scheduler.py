"""
Handlers administrativos do Agendador.

Seção 9 do painel: gerencia agendamentos programados.
Inclui criação, listagem, edição, exclusão, ativação/desativação,
histórico de execução e fuso horário individual.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID
import zoneinfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.scheduled_notification import ScheduledNotification
from bot.models.audit_log import AuditLog
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.notification_service import schedule_notification

logger = logging.getLogger(__name__)

router = Router()


class AdminSchedulerStates(StatesGroup):
    WAITING_DATE_TIME = State()
    WAITING_TEXT = State()
    WAITING_REPEAT = State()
    WAITING_TIMEZONE = State()
    WAITING_EDIT_TEXT = State()
    WAITING_EDIT_DATE_TIME = State()
    WAITING_EDIT_REPEAT = State()
    WAITING_EDIT_TIMEZONE = State()


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
        [create_button("✏️ Editar agendamento", "scheduler:edit_select")],
        [create_button("🗑 Excluir agendamento", "scheduler:delete_select")],
        [create_button("📜 Histórico de execução", "scheduler:history")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# CRIAÇÃO
# ----------------------------------------------------------------------

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
    """Recebe repetição e pede fuso horário."""
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
    await state.set_state(AdminSchedulerStates.WAITING_TIMEZONE)
    await message.answer(
        "Digite o fuso horário (ex: America/Sao_Paulo) ou 'padrão' para usar o do bot:"
    )


@router.message(AdminSchedulerStates.WAITING_TIMEZONE)
async def process_scheduler_timezone(message: Message, state: FSMContext):
    """Recebe fuso e cria agendamento."""
    tz_str = message.text.strip()
    if tz_str.lower() == "padrão":
        tz_str = settings.TIMEZONE

    # Valida fuso
    try:
        zoneinfo.ZoneInfo(tz_str)
    except Exception:
        await message.answer("Fuso horário inválido. Use ex: America/Sao_Paulo")
        return

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

        notification = await schedule_notification(
            session=session,
            tenant_id=tenant.id,
            title="Agendamento",
            message_text=msg_text,
            run_at=run_at,
            repeat_interval_minutes=repeat_interval,
            timezone_str=tz_str,
        )

    await state.clear()
    await message.answer(f"✅ Agendamento criado para {run_at.strftime('%d/%m/%Y %H:%M')}.")


# ----------------------------------------------------------------------
# LISTAGEM
# ----------------------------------------------------------------------

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

        notifications = (await session.execute(
            select(ScheduledNotification).where(
                ScheduledNotification.tenant_id == tenant.id,
                ScheduledNotification.deleted_at.is_(None),
            ).order_by(ScheduledNotification.run_at.asc()).limit(10)
        )).scalars().all()

    if not notifications:
        text = "Nenhum agendamento encontrado."
    else:
        text = "📋 Agendamentos:\n\n"
        for n in notifications:
            status_emoji = "🟢" if n.status == "PENDING" else "🔴"
            tz = getattr(n, "timezone_str", settings.TIMEZONE)
            repeat = f" (repete a cada {n.repeat_interval_minutes} min)" if n.repeat_interval_minutes else ""
            text += f"{status_emoji} {n.run_at.strftime('%d/%m/%Y %H:%M')} {tz} - {n.title}{repeat}\n"

    buttons = [[create_button("🔙 VOLTAR", "scheduler:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# EDIÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "scheduler:edit_select")
async def scheduler_edit_select(callback: CallbackQuery, state: FSMContext):
    """Lista agendamentos para edição."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        notifications = (await session.execute(
            select(ScheduledNotification).where(
                ScheduledNotification.tenant_id == tenant.id,
                ScheduledNotification.deleted_at.is_(None),
            ).order_by(ScheduledNotification.run_at.asc())
        )).scalars().all()

    if not notifications:
        await callback.answer("Nenhum agendamento para editar.")
        return

    text = "Selecione o agendamento para editar:"
    buttons = []
    for n in notifications:
        buttons.append([create_button(f"{n.title} - {n.run_at.strftime('%d/%m/%Y %H:%M')}", f"scheduler:edit_menu:{n.id}")])
    buttons.append([create_button("🔙 VOLTAR", "scheduler:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("scheduler:edit_menu:"))
async def scheduler_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de edição para um agendamento específico."""
    notification_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        notification = (await session.execute(
            select(ScheduledNotification).where(
                ScheduledNotification.id == notification_id,
                ScheduledNotification.tenant_id == tenant.id,
            )
        )).scalar_one_or_none()

    if notification is None:
        await callback.answer("Agendamento não encontrado.")
        return

    await state.update_data(edit_notification_id=str(notification.id))

    tz = getattr(notification, "timezone_str", settings.TIMEZONE)
    text = (
        f"✏️ Editando agendamento:\n\n"
        f"Título: {notification.title}\n"
        f"Texto: {notification.message_text[:50]}{'...' if len(notification.message_text) > 50 else ''}\n"
        f"Data/hora: {notification.run_at.strftime('%d/%m/%Y %H:%M')}\n"
        f"Fuso: {tz}\n"
        f"Recorrência: {notification.repeat_interval_minutes or 'Sem'}\n"
        f"Status: {notification.status}\n\n"
        "Escolha o que editar:"
    )
    buttons = [
        [create_button("📝 Texto", "scheduler:edit_text")],
        [create_button("🕒 Data/hora", "scheduler:edit_datetime")],
        [create_button("🔁 Recorrência", "scheduler:edit_repeat")],
        [create_button("🌐 Fuso horário", "scheduler:edit_timezone")],
        [create_button("Ativar/Desativar", "scheduler:toggle_active")],
        [create_button("🔙 VOLTAR", "scheduler:edit_select")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


async def _edit_field_start(callback: CallbackQuery, state: FSMContext, next_state: State, title: str):
    """Inicia edição de um campo."""
    await state.set_state(next_state)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "scheduler:edit_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "scheduler:edit_text")
async def edit_text_start(callback: CallbackQuery, state: FSMContext):
    await _edit_field_start(callback, state, AdminSchedulerStates.WAITING_EDIT_TEXT, "texto")


@router.callback_query(F.data == "scheduler:edit_datetime")
async def edit_datetime_start(callback: CallbackQuery, state: FSMContext):
    await _edit_field_start(callback, state, AdminSchedulerStates.WAITING_EDIT_DATE_TIME, "data/hora (DD/MM/AAAA HH:MM)")


@router.callback_query(F.data == "scheduler:edit_repeat")
async def edit_repeat_start(callback: CallbackQuery, state: FSMContext):
    await _edit_field_start(callback, state, AdminSchedulerStates.WAITING_EDIT_REPEAT, "recorrência (minutos, 0 = sem)")


@router.callback_query(F.data == "scheduler:edit_timezone")
async def edit_timezone_start(callback: CallbackQuery, state: FSMContext):
    await _edit_field_start(callback, state, AdminSchedulerStates.WAITING_EDIT_TIMEZONE, "fuso horário (ex: America/Sao_Paulo)")


@router.message(AdminSchedulerStates.WAITING_EDIT_TEXT)
async def process_edit_text(message: Message, state: FSMContext):
    """Salva novo texto."""
    new_text = message.text.strip()
    if not new_text:
        await message.answer("Texto vazio.")
        return

    data = await state.get_data()
    notification_id = UUID(data["edit_notification_id"])
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

        notification = (await session.execute(
            select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
        )).scalar_one_or_none()
        if notification:
            notification.message_text = new_text
            await session.commit()
            await message.answer("✅ Texto atualizado.")
        else:
            await message.answer("Agendamento não encontrado.")

    await state.clear()


@router.message(AdminSchedulerStates.WAITING_EDIT_DATE_TIME)
async def process_edit_datetime(message: Message, state: FSMContext):
    """Salva nova data/hora."""
    try:
        new_dt = datetime.strptime(message.text.strip(), "%d/%m/%Y %H:%M")
        new_dt = new_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer("Data inválida.")
        return

    data = await state.get_data()
    notification_id = UUID(data["edit_notification_id"])
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

        notification = (await session.execute(
            select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
        )).scalar_one_or_none()
        if notification:
            notification.run_at = new_dt
            await session.commit()
            await message.answer("✅ Data/hora atualizada.")
        else:
            await message.answer("Agendamento não encontrado.")

    await state.clear()


@router.message(AdminSchedulerStates.WAITING_EDIT_REPEAT)
async def process_edit_repeat(message: Message, state: FSMContext):
    """Salva nova recorrência."""
    try:
        repeat = int(message.text.strip())
        if repeat < 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido.")
        return

    data = await state.get_data()
    notification_id = UUID(data["edit_notification_id"])
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

        notification = (await session.execute(
            select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
        )).scalar_one_or_none()
        if notification:
            notification.repeat_interval_minutes = repeat if repeat > 0 else None
            await session.commit()
            await message.answer("✅ Recorrência atualizada.")
        else:
            await message.answer("Agendamento não encontrado.")

    await state.clear()


@router.message(AdminSchedulerStates.WAITING_EDIT_TIMEZONE)
async def process_edit_timezone(message: Message, state: FSMContext):
    """Salva novo fuso horário."""
    tz_str = message.text.strip()
    try:
        zoneinfo.ZoneInfo(tz_str)
    except Exception:
        await message.answer("Fuso horário inválido.")
        return

    data = await state.get_data()
    notification_id = UUID(data["edit_notification_id"])
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

        notification = (await session.execute(
            select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
        )).scalar_one_or_none()
        if notification:
            # Assume que o modelo tem timezone_str
            notification.timezone_str = tz_str
            await session.commit()
            await message.answer("✅ Fuso horário atualizado.")
        else:
            await message.answer("Agendamento não encontrado.")

    await state.clear()


# ----------------------------------------------------------------------
# TOGGLE ATIVO/INATIVO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "scheduler:toggle_active")
async def toggle_active(callback: CallbackQuery, state: FSMContext):
    """Alterna status ativo/inativo do agendamento."""
    data = await state.get_data()
    notification_id = UUID(data["edit_notification_id"])

    tenant, admin = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, admin.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        notification = (await session.execute(
            select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
        )).scalar_one_or_none()
        if notification:
            # Alterna entre PENDING e CANCELLED como ativo/inativo
            if notification.status == "CANCELLED":
                notification.status = "PENDING"
            else:
                notification.status = "CANCELLED"
            await session.commit()
            await callback.answer(f"Agendamento {'ativado' if notification.status == 'PENDING' else 'desativado'}.")
        else:
            await callback.answer("Agendamento não encontrado.")

    await scheduler_edit_menu(callback, state)


# ----------------------------------------------------------------------
# EXCLUSÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "scheduler:delete_select")
async def scheduler_delete_select(callback: CallbackQuery, state: FSMContext):
    """Lista agendamentos para exclusão."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        notifications = (await session.execute(
            select(ScheduledNotification).where(
                ScheduledNotification.tenant_id == tenant.id,
                ScheduledNotification.deleted_at.is_(None),
            )
        )).scalars().all()

    if not notifications:
        await callback.answer("Nenhum agendamento para excluir.")
        return

    text = "Selecione o agendamento para excluir:"
    buttons = []
    for n in notifications:
        buttons.append([create_button(f"{n.title} - {n.run_at.strftime('%d/%m/%Y %H:%M')}", f"scheduler:delete_confirm:{n.id}")])
    buttons.append([create_button("🔙 VOLTAR", "scheduler:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("scheduler:delete_confirm:"))
async def scheduler_delete_confirm(callback: CallbackQuery, state: FSMContext):
    """Exclui agendamento selecionado (soft delete)."""
    notification_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        notification = (await session.execute(
            select(ScheduledNotification).where(
                ScheduledNotification.id == notification_id,
                ScheduledNotification.tenant_id == tenant.id,
            )
        )).scalar_one_or_none()
        if notification:
            notification.soft_delete()
            await session.commit()
            await callback.answer("Agendamento excluído.")
        else:
            await callback.answer("Agendamento não encontrado.")

    await scheduler_main(callback, state)


# ----------------------------------------------------------------------
# HISTÓRICO DE EXECUÇÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "scheduler:history")
async def scheduler_history(callback: CallbackQuery, state: FSMContext):
    """Exibe histórico de execuções via AuditLog."""
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
            .where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action == "scheduled_notification.run",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not logs:
        text = "Nenhuma execução registrada."
    else:
        text = "📜 Histórico de execuções:\n\n"
        for log in logs:
            text += f"{log.created_at.strftime('%d/%m/%Y %H:%M')} - {log.description}\n"

    buttons = [[create_button("🔙 VOLTAR", "scheduler:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
