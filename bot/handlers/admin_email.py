"""
Handlers administrativos de E-mail.

Seção 19 do painel: gerencia configurações de e-mail.
Inclui SMTP, remetente, nome, códigos de verificação, expiração,
tentativas, templates (confirmação, entrega, recuperação, acesso)
e links temporários.
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


class AdminEmailStates(StatesGroup):
    WAITING_VALUE = State()
    WAITING_TEMPLATE_SUBJECT = State()
    WAITING_TEMPLATE_BODY = State()


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


# ----------------------------------------------------------------------
# MENU PRINCIPAL
# ----------------------------------------------------------------------

@router.callback_query(F.data == "email_admin:main")
async def email_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de e-mail."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        smtp_host = await _get_setting(session, tenant.id, "smtp_host") or "Não configurado"
        smtp_port = await _get_setting(session, tenant.id, "smtp_port") or "587"
        smtp_user = await _get_setting(session, tenant.id, "smtp_user") or "Não configurado"
        smtp_from = await _get_setting(session, tenant.id, "smtp_from") or "Não configurado"
        smtp_from_name = await _get_setting(session, tenant.id, "smtp_from_name") or "Larizinha Store"
        verification_expiration = await _get_setting(session, tenant.id, "email_code_expiration_minutes") or "10"
        max_attempts = await _get_setting(session, tenant.id, "email_code_max_attempts") or "5"
        interval_between_codes = await _get_setting(session, tenant.id, "email_code_interval_seconds") or "60"
        link_expiration = await _get_setting(session, tenant.id, "email_link_expiration_minutes") or "60"

    text = (
        "📧 CONFIGURAÇÃO DE E-MAIL\n\n"
        f"SMTP Host: <b>{smtp_host}</b>\n"
        f"SMTP Port: <b>{smtp_port}</b>\n"
        f"SMTP User: <b>{smtp_user}</b>\n"
        f"Remetente: <b>{smtp_from}</b>\n"
        f"Nome do remetente: <b>{smtp_from_name}</b>\n"
        f"Expiração do código: <b>{verification_expiration} min</b>\n"
        f"Máx. tentativas: <b>{max_attempts}</b>\n"
        f"Intervalo entre códigos: <b>{interval_between_codes} seg</b>\n"
        f"Expiração de links: <b>{link_expiration} min</b>\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("SMTP Host", "email_admin:set_smtp_host")],
        [create_button("SMTP Port", "email_admin:set_smtp_port")],
        [create_button("SMTP User", "email_admin:set_smtp_user")],
        [create_button("Remetente", "email_admin:set_smtp_from")],
        [create_button("Nome do remetente", "email_admin:set_smtp_from_name")],
        [create_button("Expiração do código", "email_admin:set_code_expiration")],
        [create_button("Máx. tentativas", "email_admin:set_max_attempts")],
        [create_button("Intervalo entre códigos", "email_admin:set_interval")],
        [create_button("Expiração de links", "email_admin:set_link_expiration")],
        [create_button("📋 Templates", "email_admin:templates_menu")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# EDIÇÃO DE VALORES SIMPLES
# ----------------------------------------------------------------------

async def _edit_email_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração de e-mail."""
    await state.set_state(AdminEmailStates.WAITING_VALUE)
    await state.update_data(email_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "email_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "email_admin:set_smtp_host")
async def set_smtp_host(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "smtp_host", "SMTP Host")


@router.callback_query(F.data == "email_admin:set_smtp_port")
async def set_smtp_port(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "smtp_port", "SMTP Port")


@router.callback_query(F.data == "email_admin:set_smtp_user")
async def set_smtp_user(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "smtp_user", "SMTP User")


@router.callback_query(F.data == "email_admin:set_smtp_from")
async def set_smtp_from(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "smtp_from", "Remetente (e-mail)")


@router.callback_query(F.data == "email_admin:set_smtp_from_name")
async def set_smtp_from_name(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "smtp_from_name", "Nome do remetente")


@router.callback_query(F.data == "email_admin:set_code_expiration")
async def set_code_expiration(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "email_code_expiration_minutes", "Expiração do código (minutos)")


@router.callback_query(F.data == "email_admin:set_max_attempts")
async def set_max_attempts(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "email_code_max_attempts", "Máx. tentativas")


@router.callback_query(F.data == "email_admin:set_interval")
async def set_interval(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "email_code_interval_seconds", "Intervalo entre códigos (segundos)")


@router.callback_query(F.data == "email_admin:set_link_expiration")
async def set_link_expiration(callback: CallbackQuery, state: FSMContext):
    await _edit_email_setting(callback, state, "email_link_expiration_minutes", "Expiração de links (minutos)")


@router.message(AdminEmailStates.WAITING_VALUE)
async def process_email_setting(message: Message, state: FSMContext):
    """Salva novo valor de configuração de e-mail."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("email_setting_key")

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
    await message.answer("✅ Configuração de e-mail atualizada.")


# ----------------------------------------------------------------------
# TEMPLATES
# ----------------------------------------------------------------------

TEMPLATE_TYPES = {
    "confirmation": "Confirmação de e-mail",
    "delivery": "Entrega de produto",
    "recovery": "Recuperação de senha",
    "access": "Acesso temporário",
}


@router.callback_query(F.data == "email_admin:templates_menu")
async def templates_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de templates de e-mail."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    text = "📋 Templates de e-mail\n\nSelecione o template:"
    buttons = []
    for code, label in TEMPLATE_TYPES.items():
        buttons.append([create_button(label, f"email_admin:template_edit:{code}")])
    buttons.append([create_button("🔙 VOLTAR", "email_admin:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("email_admin:template_edit:"))
async def template_edit(callback: CallbackQuery, state: FSMContext):
    """Menu de edição de um template específico."""
    template_code = callback.data.split(":")[-1]
    template_label = TEMPLATE_TYPES.get(template_code, template_code)

    await state.update_data(email_template_code=template_code)
    await state.set_state(AdminEmailStates.WAITING_TEMPLATE_SUBJECT)
    text = f"Digite o assunto do template <b>{template_label}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "email_admin:templates_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminEmailStates.WAITING_TEMPLATE_SUBJECT)
async def process_template_subject(message: Message, state: FSMContext):
    """Recebe assunto e pede corpo."""
    subject = message.text.strip()
    if not subject:
        await message.answer("Assunto vazio.")
        return

    await state.update_data(email_template_subject=subject)
    await state.set_state(AdminEmailStates.WAITING_TEMPLATE_BODY)
    await message.answer("Digite o corpo do e-mail (pode usar placeholders):")


@router.message(AdminEmailStates.WAITING_TEMPLATE_BODY)
async def process_template_body(message: Message, state: FSMContext):
    """Recebe corpo e salva template."""
    body = message.text.strip()
    if not body:
        await message.answer("Corpo vazio.")
        return

    data = await state.get_data()
    template_code = data.get("email_template_code")
    subject = data.get("email_template_subject")

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

        # Salva assunto e corpo em Settings
        await _set_setting(session, tenant.id, f"email_template_{template_code}_subject", subject)
        await _set_setting(session, tenant.id, f"email_template_{template_code}_body", body)

    await state.clear()
    await message.answer("✅ Template salvo com sucesso!")


# ----------------------------------------------------------------------
# LINKS TEMPORÁRIOS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "email_admin:links_menu")
async def links_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de links temporários."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        link_expiration = await _get_setting(session, tenant.id, "email_link_expiration_minutes") or "60"

    text = (
        "🔗 Links temporários\n\n"
        f"Expiração atual: {link_expiration} minutos\n\n"
        "Essa configuração define por quanto tempo os links de acesso/ativação enviados por e-mail permanecem válidos."
    )
    buttons = [
        [create_button("Alterar expiração", "email_admin:set_link_expiration")],
        [create_button("🔙 VOLTAR", "email_admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
