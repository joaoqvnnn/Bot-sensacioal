"""
Handlers administrativos de mensagens e mídias.

Permite ao administrador:
- Editar texto da home, canal obrigatório, catálogo, etc.
- Configurar URL de imagem para home e WhatsApp
- Gerenciar templates de mensagens (criar/editar/remover)

Tudo com edição da mesma mensagem, botões de voltar e dados reais.
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
from bot.models.message_template import MessageTemplate
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user
from bot.services.admin_service import is_admin_user  # service para checar permissão

logger = logging.getLogger(__name__)

router = Router()


class AdminMessageStates(StatesGroup):
    WAITING_SETTING_VALUE = State()
    WAITING_TEMPLATE_CODE = State()
    WAITING_TEMPLATE_TEXT = State()
    WAITING_IMAGE_URL = State()


async def _get_tenant_and_user(callback: CallbackQuery):
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


async def _is_admin(session, tenant_id, user_id) -> bool:
    """Verifica se o usuário é admin/dono."""
    # Utiliza service; mas para simplificar, importa direto
    from bot.models.admin_user import AdminUser

    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True
    admin = (await session.execute(
        select(AdminUser).where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.user_id == user_id,
            AdminUser.is_active == True,
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


async def _get_setting(session, tenant_id, key: str) -> Optional[str]:
    """Busca valor de configuração."""
    stmt = select(Settings).where(
        Settings.tenant_id == tenant_id,
        Settings.key == key,
        Settings.deleted_at.is_(None),
    )
    setting = (await session.execute(stmt)).scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(session, tenant_id, key: str, value: str) -> None:
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


@router.callback_query(F.data == "admin:messages")
async def show_messages_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de edição de mensagens e mídias."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Obtém valores atuais
        home_text = await _get_setting(session, tenant.id, "home_text")
        channel_required_text = await _get_setting(session, tenant.id, "channel_required_text")
        home_image_url = await _get_setting(session, tenant.id, "home_image_url")
        whatsapp_image_url = await _get_setting(session, tenant.id, "whatsapp_image_url")

    text = (
        "✏️ Edição de Mensagens e Mídias\n\n"
        f"🏠 Texto da Home: {'Sim' if home_text else 'Padrão'}\n"
        f"❗ Texto Canal Obrigatório: {'Sim' if channel_required_text else 'Padrão'}\n"
        f"🖼️ Imagem Home: {'Configurada' if home_image_url else 'Nenhuma'}\n"
        f"📱 Imagem WhatsApp: {'Configurada' if whatsapp_image_url else 'Nenhuma'}\n\n"
        "Selecione o que deseja editar:"
    )

    buttons = [
        [create_button("🏠 Editar Home", "admin:edit_home_text")],
        [create_button("❗ Editar Canal Obrigatório", "admin:edit_channel_required_text")],
        [create_button("🖼️ Configurar Imagem Home", "admin:set_home_image")],
        [create_button("📱 Configurar Imagem WhatsApp", "admin:set_whatsapp_image")],
        [create_button("📁 Gerenciar Templates", "admin:list_templates")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:edit_home_text")
async def edit_home_text(callback: CallbackQuery, state: FSMContext):
    """Pede novo texto da home."""
    await state.set_state(AdminMessageStates.WAITING_SETTING_VALUE)
    await state.update_data(setting_key="home_text")
    text = "Digite o novo texto para a Home (pode usar placeholders como {user_id}, {balance}):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:messages")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:edit_channel_required_text")
async def edit_channel_required_text(callback: CallbackQuery, state: FSMContext):
    """Pede novo texto para verificação de canal."""
    await state.set_state(AdminMessageStates.WAITING_SETTING_VALUE)
    await state.update_data(setting_key="channel_required_text")
    text = "Digite o novo texto para a verificação de canal:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:messages")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:set_home_image")
async def set_home_image(callback: CallbackQuery, state: FSMContext):
    """Pede URL da imagem da home."""
    await state.set_state(AdminMessageStates.WAITING_IMAGE_URL)
    await state.update_data(image_key="home_image_url")
    text = "Envie a URL da imagem que deseja usar na Home.\n(Ex: https://exemplo.com/imagem.jpg)"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:messages")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:set_whatsapp_image")
async def set_whatsapp_image(callback: CallbackQuery, state: FSMContext):
    """Pede URL da imagem do WhatsApp."""
    await state.set_state(AdminMessageStates.WAITING_IMAGE_URL)
    await state.update_data(image_key="whatsapp_image_url")
    text = "Envie a URL da imagem que deseja usar no WhatsApp.\n(Ex: https://exemplo.com/imagem.jpg)"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:messages")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminMessageStates.WAITING_SETTING_VALUE)
async def process_setting_value(message: Message, state: FSMContext):
    """Salva o novo texto da configuração."""
    new_value = message.text.strip() if message.text else ""
    data = await state.get_data()
    setting_key = data.get("setting_key")

    tenant, user = await _get_tenant_and_user(message)
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


@router.message(AdminMessageStates.WAITING_IMAGE_URL)
async def process_image_url(message: Message, state: FSMContext):
    """Salva a URL da imagem."""
    image_url = message.text.strip() if message.text else ""
    data = await state.get_data()
    image_key = data.get("image_key")

    tenant, user = await _get_tenant_and_user(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return
        await _set_setting(session, tenant.id, image_key, image_url)

    await state.clear()
    await message.answer("✅ Imagem configurada com sucesso!")


@router.callback_query(F.data == "admin:list_templates")
async def list_templates(callback: CallbackQuery, state: FSMContext):
    """Lista templates de mensagens existentes."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        stmt = select(MessageTemplate).where(
            MessageTemplate.tenant_id == tenant.id,
            MessageTemplate.deleted_at.is_(None),
        ).order_by(MessageTemplate.code)
        result = await session.execute(stmt)
        templates = list(result.scalars().all())

    if not templates:
        text = "Nenhum template cadastrado."
    else:
        text = "📁 Templates de mensagens:\n"
        for tpl in templates:
            text += f"• {tpl.code}\n"

    buttons = [
        [create_button("➕ Novo Template", "admin:create_template")],
        [create_button("🔙 VOLTAR", "admin:messages")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:create_template")
async def create_template(callback: CallbackQuery, state: FSMContext):
    """Pede código e texto para novo template."""
    await state.set_state(AdminMessageStates.WAITING_TEMPLATE_CODE)
    text = "Digite o código do template (ex: welcome, catalog):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:list_templates")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminMessageStates.WAITING_TEMPLATE_CODE)
async def process_template_code(message: Message, state: FSMContext):
    """Recebe código do template e pede texto."""
    code = message.text.strip() if message.text else ""
    if not code:
        await message.answer("Código não pode ser vazio.")
        return

    await state.update_data(template_code=code)
    await state.set_state(AdminMessageStates.WAITING_TEMPLATE_TEXT)
    await message.answer("Digite o conteúdo do template (pode usar placeholders):")


@router.message(AdminMessageStates.WAITING_TEMPLATE_TEXT)
async def process_template_text(message: Message, state: FSMContext):
    """Salva o novo template."""
    content = message.text.strip() if message.text else ""
    data = await state.get_data()
    code = data.get("template_code")

    tenant, user = await _get_tenant_and_user(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("Acesso negado.")
            await state.clear()
            return

        # Verifica duplicidade
        existing = (await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.tenant_id == tenant.id,
                MessageTemplate.code == code,
                MessageTemplate.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if existing:
            await message.answer("Já existe template com esse código.")
            await state.clear()
            return

        new_tpl = MessageTemplate(
            tenant_id=tenant.id,
            code=code,
            text=content,
        )
        session.add(new_tpl)
        await session.commit()

    await state.clear()
    await message.answer("✅ Template criado com sucesso!")
