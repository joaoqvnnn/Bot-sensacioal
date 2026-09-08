"""
Handlers do painel administrativo principal.

Fornece o menu inicial do administrador, com dashboard e navegação
para todas as seções. Acesso via botão no menu principal ou comando /admin.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import func, select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.order import Order
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


# ----------------------------------------------------------------------
# Lista de seções administrativas (título, callback)
# ----------------------------------------------------------------------
ADMIN_SECTIONS = [
    ("🏠 Configurações Gerais", "admin:general"),
    ("📝 Editor de Textos", "admin:editor_textos"),
    ("🔘 Configuração dos Botões", "admin:buttons"),
    ("🧩 Placeholders", "admin:placeholders"),
    ("👑 Administradores", "admins:main"),
    ("👥 Usuários", "admin:manage_users"),
    ("🎁 Bônus de Registro", "admin:bonus"),
    ("📢 Transmissões", "broadcast:main"),
    ("📅 Agendador", "scheduler:main"),
    ("🛍️ Categorias", "categories:main"),
    ("📦 Produtos", "products:main"),
    ("📦 Estoque / Logins", "inventory:main"),
    ("🔒 Reserva de Estoque", "reservation:main"),
    ("💳 Pix / Pagamentos", "pix_admin:main"),
    ("💰 Carteira / Saldo", "wallet_admin:main"),
    ("💎 Afiliados", "aff_admin:main"),
    ("💸 Saques", "withdrawals_admin:main"),
    ("🏦 Contas Bancárias", "bank_admin:main"),
    ("📧 E-mail", "email_admin:main"),
    ("📱 WhatsApp", "whatsapp_admin:main"),
    ("🤖 IA", "ai_admin:main"),
    ("🔎 Pesquisa de Serviços", "search_admin:main"),
    ("🏆 Rankings", "rankings_admin:main"),
    ("⚠️ Alertas de Estoque", "alerts_admin:main"),
    ("🛡️ Anti-flood / Segurança", "sec_admin:main"),
    ("🔐 Segurança da Plataforma", "platform_sec:main"),
    ("📋 Logs e Auditoria", "logs_admin:main"),
    ("🧩 Configuração do Mini App", "miniapp_admin:main"),
    ("🏢 Multi-tenant / Aluguel", "mt:main"),
    ("🔄 Atualizações", "updates_admin:main"),
    ("🧪 Integridade do Sistema", "integrity:main"),
]


async def _get_tenant_and_user_from_callback(callback: CallbackQuery):
    """Obtém tenant e usuário a partir do callback."""
    factory = get_async_session_factory()
    async with factory() as session:
        tenant = await get_tenant_for_bot(session, settings.TELEGRAM_BOT_USERNAME)
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
    factory = get_async_session_factory()
    async with factory() as session:
        tenant = await get_tenant_for_bot(session, settings.TELEGRAM_BOT_USERNAME)
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


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Comando /admin para abrir o painel administrativo."""
    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("⚠️ Sistema indisponível.")
        return

    factory = get_async_session_factory()
    async with factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await message.answer("🚫 Acesso negado.")
            return

    await show_admin_main_message(message, tenant, user)


async def show_admin_main_message(message: Message, tenant, user):
    """Exibe o menu principal administrativo em uma nova mensagem."""
    factory = get_async_session_factory()
    async with factory() as session:
        total_users = (await session.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant.id,
                User.deleted_at.is_(None)
            )
        )).scalar_one()

        total_revenue = (await session.execute(
            select(func.sum(Order.total_cents)).where(
                Order.tenant_id == tenant.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None)
            )
        )).scalar_one() or 0

        total_sales = (await session.execute(
            select(func.count(Order.id)).where(
                Order.tenant_id == tenant.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None)
            )
        )).scalar_one()

    text = (
        "⚙️ CONFIGURAÇÕES ADMINISTRATIVAS\n"
        f"Admin: {'Sim' if user.is_admin or user.is_owner else 'Não'}\n"
        f"Dono: {'Sim' if user.is_owner else 'Não'}\n\n"
        "📊 Dashboard:\n"
        f"👥 Usuários: {total_users}\n"
        f"💰 Receita total: {cents_to_brl(int(total_revenue))}\n"
        f"🛒 Vendas: {total_sales}\n\n"
        "Selecione uma seção:"
    )

    buttons = []
    per_page = 8
    total_sections = len(ADMIN_SECTIONS)
    page = 1
    start = 0
    end = per_page
    for title, callback_data in ADMIN_SECTIONS[start:end]:
        buttons.append([create_button(title, callback_data)])

    nav_buttons = []
    if page < (total_sections + per_page - 1) // per_page:
        nav_buttons.append(create_button("Próxima ➡️", "admin:page:2"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([create_button("🔙 VOLTAR", "menu:back")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin:main")
@router.callback_query(F.data.startswith("admin:page:"))
async def show_admin_main(callback: CallbackQuery, state: FSMContext):
    """Exibe o menu principal do painel administrativo com paginação."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    page = 1 if callback.data == "admin:main" else int(callback.data.split(":")[-1])
    per_page = 8
    total_sections = len(ADMIN_SECTIONS)
    total_pages = (total_sections + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    factory = get_async_session_factory()
    async with factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        total_users = (await session.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant.id,
                User.deleted_at.is_(None)
            )
        )).scalar_one()

        total_revenue = (await session.execute(
            select(func.sum(Order.total_cents)).where(
                Order.tenant_id == tenant.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None)
            )
        )).scalar_one() or 0

        total_sales = (await session.execute(
            select(func.count(Order.id)).where(
                Order.tenant_id == tenant.id,
                Order.status == "COMPLETED",
                Order.deleted_at.is_(None)
            )
        )).scalar_one()

    text = (
        "⚙️ CONFIGURAÇÕES ADMINISTRATIVAS\n"
        f"Admin: {'Sim' if user.is_admin or user.is_owner else 'Não'}\n"
        f"Dono: {'Sim' if user.is_owner else 'Não'}\n\n"
        "📊 Dashboard:\n"
        f"👥 Usuários: {total_users}\n"
        f"💰 Receita total: {cents_to_brl(int(total_revenue))}\n"
        f"🛒 Vendas: {total_sales}\n\n"
        f"Página {page}/{total_pages}\n"
        "Selecione uma seção:"
    )

    start = (page - 1) * per_page
    end = start + per_page
    page_sections = ADMIN_SECTIONS[start:end]

    buttons = []
    for title, callback_data in page_sections:
        buttons.append([create_button(title, callback_data)])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(create_button("⬅️ Anterior", f"admin:page:{page-1}"))
    if page < total_pages:
        nav_buttons.append(create_button("Próxima ➡️", f"admin:page:{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([create_button("🔙 VOLTAR", "menu:back")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
