"""
Handlers do painel administrativo principal.

Este módulo fornece o menu inicial do administrador, com dashboard
e navegação para todas as seções (módulos) do painel.

Cada seção possui seu próprio handler dedicado, evitando conflitos.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import func, select

from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.order import Order
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

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
    ("🔐 Segurança da Plataforma", "sec_admin:main"),
    ("📋 Logs e Auditoria", "sec_admin:main"),
    ("🧩 Configuração do Mini App", "miniapp_admin:main"),
    ("🏢 Multi-tenant / Aluguel", "mt:main"),
    ("🔄 Atualizações", "updates_admin:main"),
    ("🧪 Integridade do Sistema", "integrity:main"),
]


# ----------------------------------------------------------------------
# Menu principal com paginação
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admin:main")
@router.callback_query(F.data.startswith("admin:page:"))
async def show_admin_main(callback: CallbackQuery, state: FSMContext):
    """Exibe o menu principal do painel administrativo com paginação."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    # Determina página atual
    if callback.data == "admin:main":
        page = 1
    else:
        page = int(callback.data.split(":")[-1])

    per_page = 8
    total_sections = len(ADMIN_SECTIONS)
    total_pages = (total_sections + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    async with get_async_session_factory() as session:
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
        f"Admin: {'Sim' if await _is_admin(session, tenant.id, user.id) else 'Não'}\n"
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
