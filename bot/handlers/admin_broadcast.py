"""
Handlers administrativos de Transmissões.

Seção 8 do painel: gerencia transmissões em massa.
Inclui criação (texto, foto, vídeo, documento), listagem, agendamento,
cancelamento, pausa/retomada, velocidade de envio, retry, relatório
e fila de transmissão.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.broadcast import Broadcast
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminBroadcastStates(StatesGroup):
    WAITING_TEXT = State()
    WAITING_IMAGE = State()
    WAITING_VIDEO = State()
    WAITING_DOCUMENT = State()
    WAITING_SCHEDULE = State()
    WAITING_SPEED = State()
    WAITING_RETRY = State()


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


@router.callback_query(F.data == "broadcast:main")
async def broadcast_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de transmissões."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        pending = (await session.execute(
            select(func.count(Broadcast.id)).where(
                Broadcast.tenant_id == tenant.id,
                Broadcast.status == "PENDING",
                Broadcast.deleted_at.is_(None),
            )
        )).scalar_one()

        processing = (await session.execute(
            select(func.count(Broadcast.id)).where(
                Broadcast.tenant_id == tenant.id,
                Broadcast.status == "SENDING",
                Broadcast.deleted_at.is_(None),
            )
        )).scalar_one()

        paused = (await session.execute(
            select(func.count(Broadcast.id)).where(
                Broadcast.tenant_id == tenant.id,
                Broadcast.status == "PAUSED",
                Broadcast.deleted_at.is_(None),
            )
        )).scalar_one()

    text = (
        "📢 TRANSMISSÕES\n\n"
        f"Pendentes: {pending}\n"
        f"Enviando: {processing}\n"
        f"Pausadas: {paused}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("📝 Enviar texto", "broadcast:new:text")],
        [create_button("🖼️ Enviar foto", "broadcast:new:image")],
        [create_button("🎥 Enviar vídeo", "broadcast:new:video")],
        [create_button("📄 Enviar documento", "broadcast:new:document")],
        [create_button("📋 Listar transmissões", "broadcast:list")],
        [create_button("⚙️ Velocidade de envio", "broadcast:speed_menu")],
        [create_button("🔁 Retry automático", "broadcast:retry_menu")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# CRIAÇÃO DE TRANSMISSÃO
# ----------------------------------------------------------------------

@router.callback_query(F.data.startswith("broadcast:new:"))
async def broadcast_new(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de nova transmissão."""
    media_type = callback.data.split(":")[-1]

    await state.update_data(broadcast_type=media_type)

    if media_type == "text":
        await state.set_state(AdminBroadcastStates.WAITING_TEXT)
        text = "Digite o texto da transmissão:"
    elif media_type == "image":
        await state.set_state(AdminBroadcastStates.WAITING_IMAGE)
        text = "Envie a foto da transmissão:"
    elif media_type == "video":
        await state.set_state(AdminBroadcastStates.WAITING_VIDEO)
        text = "Envie o vídeo da transmissão:"
    elif media_type == "document":
        await state.set_state(AdminBroadcastStates.WAITING_DOCUMENT)
        text = "Envie o documento da transmissão:"
    else:
        await callback.answer("Tipo inválido.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "broadcast:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBroadcastStates.WAITING_TEXT)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Recebe texto e pergunta agendamento."""
    text = message.text.strip() if message.text else ""
    if not text:
        await message.answer("Texto vazio.")
        return

    await state.update_data(message_text=text, image_url=None, video_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer(
        "Deseja agendar? Envie data/hora (DD/MM/AAAA HH:MM) ou '0' para imediato."
    )


@router.message(AdminBroadcastStates.WAITING_IMAGE)
async def process_broadcast_image(message: Message, state: FSMContext):
    """Recebe foto."""
    if not message.photo:
        await message.answer("Envie uma foto válida.")
        return

    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(image_url=file_id, message_text=message.caption or "", video_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Foto recebida. Agendar? (DD/MM/AAAA HH:MM) ou '0'.")


@router.message(AdminBroadcastStates.WAITING_VIDEO)
async def process_broadcast_video(message: Message, state: FSMContext):
    """Recebe vídeo."""
    if not message.video:
        await message.answer("Envie um vídeo válido.")
        return

    file_id = message.video.file_id
    await state.update_data(video_url=file_id, message_text=message.caption or "", image_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Vídeo recebido. Agendar? (DD/MM/AAAA HH:MM) ou '0'.")


@router.message(AdminBroadcastStates.WAITING_DOCUMENT)
async def process_broadcast_document(message: Message, state: FSMContext):
    """Recebe documento."""
    if not message.document:
        await message.answer("Envie um documento válido.")
        return

    file_id = message.document.file_id
    await state.update_data(video_url=file_id, message_text=message.caption or "", image_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Documento recebido. Agendar? (DD/MM/AAAA HH:MM) ou '0'.")


@router.message(AdminBroadcastStates.WAITING_SCHEDULE)
async def process_broadcast_schedule(message: Message, state: FSMContext):
    """Recebe agendamento e cria a transmissão."""
    schedule_text = message.text.strip() if message.text else "0"
    scheduled_at = None
    if schedule_text != "0":
        try:
            scheduled_at = datetime.strptime(schedule_text, "%d/%m/%Y %H:%M")
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("Data inválida.")
            return

    data = await state.get_data()
    broadcast_type = data.get("broadcast_type", "text")
    message_text = data.get("message_text", "")
    image_url = data.get("image_url")
    video_url = data.get("video_url")

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

        # Valores de velocidade e retry (default)
        speed = int(await _get_setting(session, tenant.id, "broadcast_speed_per_second") or "5")
        retry = int(await _get_setting(session, tenant.id, "broadcast_retry") or "3")

        broadcast = Broadcast(
            tenant_id=tenant.id,
            title=f"Transmissão {broadcast_type}",
            message_text=message_text,
            image_url=image_url,
            video_url=video_url,
            status="PENDING",
            scheduled_at=scheduled_at,
        )
        session.add(broadcast)
        await session.commit()

    await state.clear()
    await message.answer("✅ Transmissão criada com sucesso!")


# ----------------------------------------------------------------------
# LISTAGEM E CONTROLE
# ----------------------------------------------------------------------

@router.callback_query(F.data == "broadcast:list")
async def broadcast_list(callback: CallbackQuery, state: FSMContext):
    """Lista transmissões recentes e controles."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        broadcasts = (await session.execute(
            select(Broadcast)
            .where(
                Broadcast.tenant_id == tenant.id,
                Broadcast.deleted_at.is_(None),
            )
            .order_by(Broadcast.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not broadcasts:
        text = "Nenhuma transmissão."
    else:
        text = "📋 Últimas transmissões:\n\n"
        buttons = []
        for b in broadcasts:
            status_emoji = {
                "PENDING": "🟡",
                "SENDING": "🔵",
                "PAUSED": "⏸",
                "COMPLETED": "🟢",
                "FAILED": "🔴",
                "CANCELLED": "⚫",
            }.get(b.status, "⚪")
            text += f"{status_emoji} {b.title} - {b.status}\n"
            # Adiciona controles por transmissão
            buttons.append([create_button(f"🎛 {b.title}", f"broadcast:control:{b.id}")])

    buttons.append([create_button("🔙 VOLTAR", "broadcast:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("broadcast:control:"))
async def broadcast_control(callback: CallbackQuery, state: FSMContext):
    """Menu de controle de uma transmissão."""
    broadcast_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant.id)
        )).scalar_one_or_none()

    if broadcast is None:
        await callback.answer("Transmissão não encontrada.")
        return

    text = (
        f"🎛 Controle: <b>{broadcast.title}</b>\n"
        f"Status: {broadcast.status}\n\n"
        "Escolha uma ação:"
    )
    buttons = []
    if broadcast.status in ("PENDING", "PAUSED"):
        buttons.append([create_button("▶️ Iniciar/Retomar", f"broadcast:resume:{broadcast.id}")])
    if broadcast.status == "SENDING":
        buttons.append([create_button("⏸ Pausar", f"broadcast:pause:{broadcast.id}")])
    if broadcast.status in ("PENDING", "PAUSED", "SENDING"):
        buttons.append([create_button("❌ Cancelar", f"broadcast:cancel:{broadcast.id}")])
    buttons.append([create_button("📊 Relatório", f"broadcast:report:{broadcast.id}")])
    buttons.append([create_button("🔙 VOLTAR", "broadcast:list")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("broadcast:cancel:"))
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancela transmissão."""
    broadcast_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if broadcast:
            broadcast.status = "CANCELLED"
            await session.commit()
            await callback.answer("Transmissão cancelada.")
        else:
            await callback.answer("Transmissão não encontrada.")

    await broadcast_list(callback, state)


@router.callback_query(F.data.startswith("broadcast:pause:"))
async def broadcast_pause(callback: CallbackQuery, state: FSMContext):
    """Pausa transmissão."""
    broadcast_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if broadcast:
            broadcast.status = "PAUSED"
            await session.commit()
            await callback.answer("Transmissão pausada.")
        else:
            await callback.answer("Transmissão não encontrada.")

    await broadcast_control(callback, state)


@router.callback_query(F.data.startswith("broadcast:resume:"))
async def broadcast_resume(callback: CallbackQuery, state: FSMContext):
    """Retoma transmissão pausada."""
    broadcast_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if broadcast:
            broadcast.status = "SENDING"
            await session.commit()
            await callback.answer("Transmissão retomada.")
        else:
            await callback.answer("Transmissão não encontrada.")

    await broadcast_control(callback, state)


@router.callback_query(F.data.startswith("broadcast:report:"))
async def broadcast_report(callback: CallbackQuery, state: FSMContext):
    """Exibe relatório de envio (simplificado)."""
    broadcast_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Por ora, não temos tabela de entregas por broadcast; apenas status geral.
        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant.id)
        )).scalar_one_or_none()

    if broadcast is None:
        await callback.answer("Transmissão não encontrada.")
        return

    text = (
        f"📊 Relatório da transmissão:\n\n"
        f"Título: {broadcast.title}\n"
        f"Status: {broadcast.status}\n"
        f"Criada em: {broadcast.created_at.strftime('%d/%m/%Y %H:%M')}\n"
        f"Agendada: {broadcast.scheduled_at.strftime('%d/%m/%Y %H:%M') if broadcast.scheduled_at else 'Não'}\n"
        f"Enviada: {broadcast.sent_at.strftime('%d/%m/%Y %H:%M') if broadcast.sent_at else 'Não'}\n"
        "\n(Relatório detalhado de enviados/falhas será integrado com worker)"
    )
    buttons = [[create_button("🔙 VOLTAR", "broadcast:list")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# VELOCIDADE E RETRY
# ----------------------------------------------------------------------

@router.callback_query(F.data == "broadcast:speed_menu")
async def speed_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de velocidade de envio."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, "broadcast_speed_per_second") or "5"

    text = (
        "⚙️ Velocidade de envio\n\n"
        f"Limite por segundo: {current}\n\n"
        "Digite novo valor:"
    )
    await state.set_state(AdminBroadcastStates.WAITING_SPEED)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "broadcast:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBroadcastStates.WAITING_SPEED)
async def process_speed(message: Message, state: FSMContext):
    """Salva nova velocidade."""
    try:
        speed = int(message.text.strip())
        if speed < 1 or speed > 50:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido (1-50).")
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
        await _set_setting(session, tenant.id, "broadcast_speed_per_second", str(speed))

    await state.clear()
    await message.answer(f"✅ Velocidade atualizada para {speed}/s.")


@router.callback_query(F.data == "broadcast:retry_menu")
async def retry_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de retry automático."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "broadcast_retry") or "3"

    text = (
        "🔁 Retry automático\n\n"
        f"Tentativas: {current}\n\n"
        "Digite novo número de tentativas:"
    )
    await state.set_state(AdminBroadcastStates.WAITING_RETRY)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "broadcast:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBroadcastStates.WAITING_RETRY)
async def process_retry(message: Message, state: FSMContext):
    """Salva novo valor de retry."""
    try:
        retry = int(message.text.strip())
        if retry < 0 or retry > 10:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido (0-10).")
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
        await _set_setting(session, tenant.id, "broadcast_retry", str(retry))

    await state.clear()
    await message.answer(f"✅ Retry atualizado para {retry} tentativas.")
