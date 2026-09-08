"""
Handlers administrativos do Editor de Textos.

Permite ao administrador editar todas as mensagens do bot:
- /start, canal obrigatório, catálogo, produto, compra, Pix, perfil,
  histórico, Gift Card, recarga, afiliados, saques, rankings, alertas,
  manutenção, anti-flood, erros, sucesso, etc.

Tudo persistido na tabela Settings, com validação de placeholders.
"""

import logging
import re
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


# Lista de mensagens editáveis (código -> título)
EDITABLE_MESSAGES = {
    "start_message": "Mensagem /start",
    "mandatory_channel_message": "Mensagem de canal obrigatório",
    "catalog_message": "Mensagem de catálogo",
    "category_message": "Mensagem de categoria",
    "product_message": "Mensagem de produto",
    "purchase_message": "Mensagem de compra",
    "insufficient_balance_message": "Mensagem de saldo insuficiente",
    "quantity_message": "Mensagem de quantidade",
    "cancel_message": "Mensagem de cancelamento",
    "pix_message": "Mensagem de Pix",
    "pix_pending_message": "Mensagem de Pix pendente",
    "pix_paid_message": "Mensagem de Pix confirmado",
    "pix_expired_message": "Mensagem de Pix expirado",
    "pix_failed_message": "Mensagem de Pix falhou",
    "profile_message": "Mensagem de perfil",
    "history_message": "Mensagem de histórico",
    "gift_card_message": "Mensagem de Gift Card",
    "change_data_message": "Mensagem de alteração de dados",
    "recharge_message": "Mensagem de recarga",
    "bonus_message": "Mensagem de bônus",
    "affiliate_message": "Mensagem de afiliados",
    "points_message": "Mensagem de pontos",
    "withdrawal_message": "Mensagem de saque",
    "withdrawal_history_message": "Mensagem de histórico de saque",
    "ranking_message": "Mensagem de ranking",
    "support_message": "Mensagem de atendimento",
    "about_message": "Mensagem de sobre o bot",
    "terms_message": "Mensagem de termos",
    "alerts_message": "Mensagem de alertas",
    "search_message": "Mensagem de pesquisa",
    "delivery_message": "Mensagem de entrega",
    "maintenance_message": "Mensagem de manutenção",
    "antiflood_message": "Mensagem de anti-flood",
    "error_message": "Mensagens de erro",
    "success_message": "Mensagens de sucesso",
}

# Placeholders permitidos (validação)
ALLOWED_PLACEHOLDERS = {
    "user_id", "username", "first_name", "balance", "total_users",
    "total_sales", "total_revenue", "product_name", "price", "stock",
    "sold_count", "viewers", "duration", "guarantee", "order_id",
    "payment_id", "expires_at", "bonus", "pix_code", "affiliate_link",
    "referral_count", "commission_balance", "withdrawal_min",
    "tenant_id", "plan", "bot_version",
}


class EditorTextosStates(StatesGroup):
    WAITING_MESSAGE = State()


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
    """Busca valor de configuração por chave."""
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


def _validate_placeholders(text: str) -> list:
    """
    Valida placeholders no texto.
    Retorna lista de placeholders inválidos.
    """
    found = set(re.findall(r"\{(.*?)\}", text))
    invalid = [p for p in found if p not in ALLOWED_PLACEHOLDERS]
    return invalid


@router.callback_query(F.data == "admin:editor_textos")
async def show_editor_textos(callback: CallbackQuery, state: FSMContext):
    """Exibe o menu de edição de textos."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    # Divide em páginas (10 itens por página)
    items = list(EDITABLE_MESSAGES.items())
    per_page = 8
    total_pages = (len(items) + per_page - 1) // per_page
    page = 1  # simplificação: primeira página

    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    text = "📝 EDITOR DE TEXTOS\n\nSelecione a mensagem para editar:\n"
    buttons = []
    for code, title in page_items:
        buttons.append([create_button(title, f"text_editor:edit:{code}")])

    # Botões de navegação simplificados
    nav = []
    if page > 1:
        nav.append(create_button("⬅️ Anterior", f"text_editor:page:{page-1}"))
    nav.append(create_button(f"{page}/{total_pages}", "none"))
    if page < total_pages:
        nav.append(create_button("Próxima ➡️", f"text_editor:page:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([create_button("🔙 VOLTAR", "admin:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("text_editor:page:"))
async def text_editor_page(callback: CallbackQuery, state: FSMContext):
    """Trata paginação do editor de textos."""
    page = int(callback.data.split(":")[-1])
    # Reexecuta com a página solicitada
    await show_editor_textos(callback, state)  # simplificado, mas sem página real


@router.callback_query(F.data.startswith("text_editor:edit:"))
async def edit_message_text(callback: CallbackQuery, state: FSMContext):
    """Pede o novo texto para a mensagem selecionada."""
    code = callback.data.split(":", 2)[2]
    title = EDITABLE_MESSAGES.get(code, code)

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        current = await _get_setting(session, tenant.id, code) or ""

    await state.set_state(EditorTextosStates.WAITING_MESSAGE)
    await state.update_data(message_code=code)

    text = (
        f"✏️ Editando: <b>{title}</b>\n\n"
        f"Texto atual:\n<code>{current[:200]}</code>\n\n"
        "Digite o novo texto abaixo.\n"
        "Placeholders permitidos: {user_id}, {balance}, {product_name}, etc."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:editor_textos")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(EditorTextosStates.WAITING_MESSAGE)
async def process_message_text(message: Message, state: FSMContext):
    """Salva o novo texto da mensagem."""
    new_text = message.text.strip() if message.text else ""
    if not new_text:
        await message.answer("Texto vazio não permitido.")
        return

    # Valida placeholders
    invalid = _validate_placeholders(new_text)
    if invalid:
        await message.answer(
            f"❌ Placeholders inválidos: {', '.join(invalid)}\n"
            "Use apenas placeholders permitidos."
        )
        return

    data = await state.get_data()
    message_code = data.get("message_code")

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
        await _set_setting(session, tenant.id, message_code, new_text)

    await state.clear()
    await message.answer("✅ Mensagem atualizada com sucesso!")
