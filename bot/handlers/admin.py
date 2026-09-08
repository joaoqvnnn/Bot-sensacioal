"""
Handlers administrativos.

Painel inicial do administrador/dono, com:
- Dashboard com métricas reais
- Gerenciamento de admins (adicionar, remover, listar)
- Configurações de afiliados (percentual, pontos, mínimo)
- Configurações de Pix (mínimo, máximo, bônus, expiração)

Tudo editando a mesma mensagem, com botões de voltar.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import func, select

from bot.core.config import settings
from bot.core.database import get_async_session_factory
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.admin_user import AdminUser
from bot.models.affiliate import AffiliatePoints  # se necessário
from bot.models.order import Order
from bot.models.user import User
from bot.models.tenant import Tenant
from bot.models.settings import Settings  # modelo Settings
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminStates(StatesGroup):
    WAITING_ADMIN_ID = State()
    WAITING_REMOVE_ADMIN_ID = State()
    WAITING_AFFILIATE_PERCENT = State()
    WAITING_AFFILIATE_MIN_POINTS = State()
    WAITING_PIX_MIN = State()
    WAITING_PIX_MAX = State()
    WAITING_PIX_BONUS = State()


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
    # Verifica se é owner
    user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if user and (user.is_owner or user.is_admin):
        return True

    # Verifica tabela admin_users
    admin_stmt = select(AdminUser).where(
        AdminUser.tenant_id == tenant_id,
        AdminUser.user_id == user_id,
        AdminUser.is_active == True,
        AdminUser.deleted_at.is_(None),
    )
    admin = (await session.execute(admin_stmt)).scalar_one_or_none()
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


@router.callback_query(F.data == "admin:main")
async def show_admin_main(callback: CallbackQuery, state: FSMContext):
    """Exibe o menu principal do painel administrativo."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Coleta métricas reais
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
        "⚙️ MENU DE CONFIGURAÇÕES DO BOT\n"
        f"Admin: {'Sim' if await _is_admin(session, tenant.id, user.id) else 'Não'}\n"
        f"Dono: {'Sim' if user.is_owner else 'Não'}\n\n"
        "📊 Dashboard:\n"
        f"👥 Usuários: {total_users}\n"
        f"💰 Receita total: {cents_to_brl(int(total_revenue))}\n"
        f"🛒 Vendas: {total_sales}\n\n"
        "Selecione uma opção:"
    )

    buttons = [
        [create_button("👑 CONFIGURAR ADMINS", "admin:manage_admins")],
        [create_button("💎 CONFIGURAR AFILIADOS", "admin:affiliate_settings")],
        [create_button("💳 CONFIGURAR PIX", "admin:pix_settings")],
        [create_button("👥 CONFIGURAR USUÁRIOS", "admin:manage_users")],
        [create_button("📦 CONFIGURAR LOGINS", "admin:manage_stock")],
        [create_button("🔙 VOLTAR", "menu:back")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:manage_admins")
async def manage_admins(callback: CallbackQuery, state: FSMContext):
    """Menu de gerenciamento de administradores."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Conta admins ativos
        admin_count = (await session.execute(
            select(func.count(AdminUser.id)).where(
                AdminUser.tenant_id == tenant.id,
                AdminUser.is_active == True,
                AdminUser.deleted_at.is_(None)
            )
        )).scalar_one()

    text = (
        "👑 PAINEL CONFIGURAR ADMIN\n"
        f"Administradores: {admin_count}\n"
        "Use os botões abaixo para fazer as alterações necessárias."
    )
    buttons = [
        [create_button("➕ ADICIONAR ADM", "admin:add_admin")],
        [create_button("➖ REMOVER ADM", "admin:remove_admin")],
        [create_button("👥 LISTA DE ADM", "admin:list_admins")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:add_admin")
async def add_admin(callback: CallbackQuery, state: FSMContext):
    """Pede o ID ou username do novo admin."""
    await state.set_state(AdminStates.WAITING_ADMIN_ID)
    text = "Envie o ID Telegram ou @username do novo administrador."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:manage_admins")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStates.WAITING_ADMIN_ID)
async def process_add_admin(message: Message, state: FSMContext):
    """Processa adição de admin por ID ou username."""
    from bot.services.user_service import get_tenant_for_bot, get_or_create_user
    input_value = message.text.strip() if message.text else ""
    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant is None:
            await message.answer("Sistema indisponível.")
            await state.clear()
            return

        # Se input for numérico, busca por telegram_id, senão username
        target_user = None
        if input_value.isdigit():
            stmt = select(User).where(
                User.tenant_id == tenant.id,
                User.telegram_id == int(input_value),
                User.deleted_at.is_(None),
            )
            target_user = (await session.execute(stmt)).scalar_one_or_none()
        elif input_value.startswith("@"):
            username = input_value[1:]
            stmt = select(User).where(
                User.tenant_id == tenant.id,
                User.username == username,
                User.deleted_at.is_(None),
            )
            target_user = (await session.execute(stmt)).scalar_one_or_none()

        if target_user is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        # Verifica se já é admin
        existing_admin = (await session.execute(
            select(AdminUser).where(
                AdminUser.tenant_id == tenant.id,
                AdminUser.user_id == target_user.id,
                AdminUser.is_active == True,
            )
        )).scalar_one_or_none()
        if existing_admin:
            await message.answer("Usuário já é administrador.")
            await state.clear()
            return

        # Adiciona como admin
        new_admin = AdminUser(
            tenant_id=tenant.id,
            user_id=target_user.id,
            role="ADMIN",
            is_active=True,
            granted_at=datetime.now(timezone.utc),
            granted_by_user_id=message.from_user.id,
        )
        session.add(new_admin)
        await session.commit()

        await message.answer(f"✅ {target_user.first_name or target_user.username} agora é admin.")

    await state.clear()


@router.callback_query(F.data == "admin:list_admins")
async def list_admins(callback: CallbackQuery, state: FSMContext):
    """Lista admins ativos."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        stmt = (
            select(AdminUser, User)
            .join(User, User.id == AdminUser.user_id)
            .where(
                AdminUser.tenant_id == tenant.id,
                AdminUser.is_active == True,
                AdminUser.deleted_at.is_(None)
            )
        )
        result = await session.execute(stmt)
        admins = result.all()

    if not admins:
        text = "Nenhum admin cadastrado."
    else:
        text = "👥 Lista de administradores:\n"
        for admin, user in admins:
            text += f"• {user.first_name or user.username} (ID: {user.telegram_id})\n"

    buttons = [[create_button("🔙 VOLTAR", "admin:manage_admins")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:affiliate_settings")
async def affiliate_settings(callback: CallbackQuery, state: FSMContext):
    """Exibe e permite editar configurações de afiliados."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        # Busca valores atuais (se existirem) ou padrões
        commission_percent = await _get_setting(session, tenant.id, "affiliate_percent") or "20"
        min_points = await _get_setting(session, tenant.id, "affiliate_min_points") or "500"
        multiplier = await _get_setting(session, tenant.id, "affiliate_multiplier") or "0.01"

    text = (
        "💎 CONFIGURAÇÃO DE AFILIADOS\n\n"
        f"🧲 Comissão: {commission_percent}%\n"
        f"🔻 Pontos mínimos para converter: {min_points}\n"
        f"✖️ Multiplicador: {multiplier}\n\n"
        "Selecione o que deseja alterar:"
    )
    buttons = [
        [create_button(f"🧲 Alterar comissão ({commission_percent}%)", "admin:change_affiliate_percent")],
        [create_button(f"🔻 Alterar pontos mínimos ({min_points})", "admin:change_affiliate_min_points")],
        [create_button(f"✖️ Alterar multiplicador ({multiplier})", "admin:change_affiliate_multiplier")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:change_affiliate_percent")
async def change_affiliate_percent(callback: CallbackQuery, state: FSMContext):
    """Pede novo percentual de comissão."""
    await state.set_state(AdminStates.WAITING_AFFILIATE_PERCENT)
    text = "Digite o novo percentual de comissão (ex: 20 para 20%):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:affiliate_settings")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStates.WAITING_AFFILIATE_PERCENT)
async def process_affiliate_percent(message: Message, state: FSMContext):
    """Salva novo percentual."""
    value = message.text.strip() if message.text else ""
    try:
        percent = int(value)
        if percent < 0 or percent > 100:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido. Digite um número entre 0 e 100.")
        return

    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant:
            await _set_setting(session, tenant.id, "affiliate_percent", str(percent))
            await message.answer(f"✅ Comissão atualizada para {percent}%.")

    await state.clear()


@router.callback_query(F.data == "admin:pix_settings")
async def pix_settings(callback: CallbackQuery, state: FSMContext):
    """Exibe configurações de Pix."""
    tenant, user = await _get_tenant_and_user(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        min_dep = await _get_setting(session, tenant.id, "pix_min_deposit") or str(settings.MERCADO_PAGO_MIN_DEPOSIT)
        max_dep = await _get_setting(session, tenant.id, "pix_max_deposit") or str(settings.MERCADO_PAGO_MAX_DEPOSIT)
        bonus = await _get_setting(session, tenant.id, "pix_bonus_percent") or "0"

    text = (
        "💳 CONFIGURAÇÃO PIX\n\n"
        f"💰 Depósito mínimo: R$ {min_dep}\n"
        f"💰 Depósito máximo: R$ {max_dep}\n"
        f"🎁 Bônus: {bonus}%\n\n"
        "Escolha o que alterar:"
    )
    buttons = [
        [create_button(f"Alterar mínimo (R$ {min_dep})", "admin:change_pix_min")],
        [create_button(f"Alterar máximo (R$ {max_dep})", "admin:change_pix_max")],
        [create_button(f"Alterar bônus ({bonus}%)", "admin:change_pix_bonus")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:change_pix_min")
async def change_pix_min(callback: CallbackQuery, state: FSMContext):
    """Pede novo depósito mínimo."""
    await state.set_state(AdminStates.WAITING_PIX_MIN)
    text = "Digite o novo depósito mínimo (ex: 1.00):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:pix_settings")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminStates.WAITING_PIX_MIN)
async def process_pix_min(message: Message, state: FSMContext):
    """Salva novo mínimo."""
    value = message.text.strip() if message.text else ""
    try:
        min_cents = int(float(value.replace(",", ".")) * 100)
        if min_cents <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Valor inválido. Use formato como 1.00 ou 10,50.")
        return

    async with get_async_session_factory() as session:
        tenant = await get_tenant_for_bot(session, message.bot.username)
        if tenant:
            await _set_setting(session, tenant.id, "pix_min_deposit", f"{min_cents/100:.2f}")
            await message.answer(f"✅ Depósito mínimo atualizado para R$ {min_cents/100:.2f}.")

    await state.clear()
