"""
Handlers administrativos de Transmissões.

Seção 8 do painel: permite criar, listar e cancelar transmissões em massa.
Suporta texto, foto, vídeo e documento, com agendamento opcional.

Tudo persistido na tabela Broadcast e processado por worker.
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
            select(Broadcast).where(
                Broadcast.tenant_id == tenant.id,
                Broadcast.status == "PENDING",
                Broadcast.deleted_at.is_(None),
            )
        )).scalars().all()

    text = (
        "📢 TRANSMISSÕES\n\n"
        f"Pendentes: {len(pending)}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("📝 Enviar texto", "broadcast:new:text")],
        [create_button("🖼️ Enviar foto", "broadcast:new:image")],
        [create_button("🎥 Enviar vídeo", "broadcast:new:video")],
        [create_button("📄 Enviar documento", "broadcast:new:document")],
        [create_button("📋 Listar transmissões", "broadcast:list")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("broadcast:new:"))
async def broadcast_new(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de nova transmissão."""
    media_type = callback.data.split(":")[-1]  # text, image, video, document

    await state.update_data(broadcast_type=media_type)

    if media_type == "text":
        await state.set_state(AdminBroadcastStates.WAITING_TEXT)
        text = "Digite o texto da transmissão:"
    elif media_type == "image":
        await state.set_state(AdminBroadcastStates.WAITING_IMAGE)
        text = "Envie a foto da transmissão (como imagem):"
    elif media_type == "video":
        await state.set_state(AdminBroadcastStates.WAITING_VIDEO)
        text = "Envie o vídeo da transmissão (como vídeo):"
    elif media_type == "document":
        await state.set_state(AdminBroadcastStates.WAITING_DOCUMENT)
        text = "Envie o documento da transmissão (como arquivo):"
    else:
        await callback.answer("Tipo inválido.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "broadcast:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminBroadcastStates.WAITING_TEXT)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Recebe texto e pergunta se deseja agendar."""
    text = message.text.strip() if message.text else ""
    if not text:
        await message.answer("Texto vazio.")
        return

    await state.update_data(message_text=text, image_url=None, video_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer(
        "Deseja agendar? Envie a data/hora (DD/MM/AAAA HH:MM) ou '0' para enviar imediatamente."
    )


@router.message(AdminBroadcastStates.WAITING_IMAGE)
async def process_broadcast_image(message: Message, state: FSMContext):
    """Recebe foto e salva ID/URL."""
    if not message.photo:
        await message.answer("Envie uma foto válida.")
        return

    # Pega a foto de maior resolução
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(image_url=file_id, message_text=message.caption or "", video_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Foto recebida. Deseja agendar? Envie data/hora ou '0'.")


@router.message(AdminBroadcastStates.WAITING_VIDEO)
async def process_broadcast_video(message: Message, state: FSMContext):
    """Recebe vídeo e salva ID/URL."""
    if not message.video:
        await message.answer("Envie um vídeo válido.")
        return

    video = message.video
    file_id = video.file_id
    await state.update_data(video_url=file_id, message_text=message.caption or "", image_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Vídeo recebido. Deseja agendar? Envie data/hora ou '0'.")


@router.message(AdminBroadcastStates.WAITING_DOCUMENT)
async def process_broadcast_document(message: Message, state: FSMContext):
    """Recebe documento e salva ID/URL."""
    if not message.document:
        await message.answer("Envie um documento válido.")
        return

    document = message.document
    file_id = document.file_id
    await state.update_data(video_url=file_id, message_text=message.caption or "", image_url=None)
    await state.set_state(AdminBroadcastStates.WAITING_SCHEDULE)
    await message.answer("Documento recebido. Deseja agendar? Envie data/hora ou '0'.")


@router.message(AdminBroadcastStates.WAITING_SCHEDULE)
async def process_broadcast_schedule(message: Message, state: FSMContext):
    """Recebe agendamento e cria Broadcast."""
    schedule_text = message.text.strip() if message.text else "0"
    scheduled_at = None
    if schedule_text != "0":
        try:
            scheduled_at = datetime.strptime(schedule_text, "%d/%m/%Y %H:%M")
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("Data/hora inválida. Use DD/MM/AAAA HH:MM ou 0.")
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


@router.callback_query(F.data == "broadcast:list")
async def broadcast_list(callback: CallbackQuery, state: FSMContext):
    """Lista transmissões recentes."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        stmt = select(Broadcast).where(
            Broadcast.tenant_id == tenant.id,
            Broadcast.deleted_at.is_(None),
        ).order_by(Broadcast.created_at.desc()).limit(10)
        result = await session.execute(stmt)
        broadcasts = list(result.scalars().all())

    if not broadcasts:
        text = "Nenhuma transmissão encontrada."
    else:
        text = "📋 Últimas transmissões:\n\n"
        for b in broadcasts:
            status_emoji = "🟢" if b.status == "COMPLETED" else "🔴"
            sched = f" (agendada para {b.scheduled_at.strftime('%d/%m/%Y %H:%M')})" if b.scheduled_at else ""
            text += f"{status_emoji} {b.title}{sched}\n"

    buttons = [[create_button("🔙 VOLTAR", "broadcast:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
