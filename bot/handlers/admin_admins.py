"""
Handlers administrativos de Administradores.

Seção 5 do painel: gerencia administradores com permissões individuais.
Permite adicionar, remover, listar, definir proprietário, bloquear e
alterar permissões específicas (financeiro, estoque, usuários, etc.).

Tudo com edição na mesma mensagem e botões de voltar.
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
from bot.models.admin_user import AdminUser
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminAdminsStates(StatesGroup):
    WAITING_ADMIN_TELEGRAM_ID = State()
    WAITING_ADMIN_ROLE = State()
    WAITING_PERMISSION_TOGGLE = State()


PERMISSION_LABELS = {
    "can_manage_finance": "💰 Financeiro",
    "can_manage_stock": "📦 Estoque",
    "can_manage_users": "👥 Usuários",
    "can_manage_support": "🎧 Suporte",
    "can_manage_settings": "⚙️ Configurações",
    "can_manage_broadcast": "📢 Broadcast",
    "can_manage_withdrawals": "💸 Saques",
    "can_manage_affiliates": "💎 Afiliados",
    "can_manage_products": "🛍️ Produtos",
    "can_manage_payments": "💳 Pagamentos",
}


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
    """Verifica se o usuário tem qualquer papel administrativo."""
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
            AdminUser.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return admin is not None


async def _is_owner(session, tenant_id: UUID, user_id: UUID) -> bool:
    """Verifica se o usuário é dono."""
    user = (await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    return user.is_owner if user else False


async def _edit_or_answer(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """Edita a mensagem atual, se possível."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


async def _list_admins(session, tenant_id: UUID):
    """Retorna lista de AdminUser com User associado."""
    stmt = (
        select(AdminUser, User)
        .join(User, User.id == AdminUser.user_id)
        .where(
            AdminUser.tenant_id == tenant_id,
            AdminUser.is_active == True,
            AdminUser.deleted_at.is_(None),
        )
        .order_by(AdminUser.role, User.username)
    )
    result = await session.execute(stmt)
    return result.all()


async def _format_admin_list(admins) -> str:
    """Formata a lista de administradores para exibição."""
    if not admins:
        return "Nenhum administrador cadastrado."
    lines = ["👑 Administradores:\n"]
    for admin, user in admins:
        lines.append(f"• {user.first_name or user.username} (ID: {user.telegram_id})")
        lines.append(f"  Papel: {admin.role}")
        perm_summary = []
        for perm_code, label in PERMISSION_LABELS.items():
            if getattr(admin, perm_code, False):
                perm_summary.append(label)
        if perm_summary:
            lines.append(f"  Permissões: {', '.join(perm_summary)}")
        else:
            lines.append("  Permissões: Nenhuma específica")
        lines.append("")
    return "\n".join(lines)


@router.callback_query(F.data == "admins:main")
async def show_admins_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de gerenciamento de administradores."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        admins = await _list_admins(session, tenant.id)

    text = _format_admin_list(admins)
    text += "\nSelecione uma ação:"

    buttons = [
        [create_button("➕ Adicionar administrador", "admins:add")],
        [create_button("➖ Remover administrador", "admins:remove_select")],
        [create_button("👑 Definir proprietário", "admins:set_owner_select")],
        [create_button("🔐 Permissões individuais", "admins:permissions_select")],
        [create_button("🚫 Bloquear/Desbloquear", "admins:toggle_block_select")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


# ----------------------------------------------------------------------
# ADICIONAR ADMINISTRADOR
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admins:add")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    """Inicia adição de novo administrador."""
    await state.set_state(AdminAdminsStates.WAITING_ADMIN_TELEGRAM_ID)
    text = "Envie o ID Telegram ou @username do novo administrador:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admins:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminAdminsStates.WAITING_ADMIN_TELEGRAM_ID)
async def process_admin_telegram_id(message: Message, state: FSMContext):
    """Recebe ID/username e pede o papel (ADMIN ou OWNER)."""
    input_value = message.text.strip() if message.text else ""
    tenant, current_user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await message.answer("Apenas o proprietário pode adicionar administradores.")
            await state.clear()
            return

        target_user = None
        if input_value.isdigit():
            target_user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.telegram_id == int(input_value),
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
        elif input_value.startswith("@"):
            target_user = (await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.username == input_value[1:],
                    User.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

        if target_user is None:
            await message.answer("Usuário não encontrado.")
            await state.clear()
            return

        # Verifica se já é admin
        existing = (await session.execute(
            select(AdminUser).where(
                AdminUser.tenant_id == tenant.id,
                AdminUser.user_id == target_user.id,
                AdminUser.is_active == True,
            )
        )).scalar_one_or_none()
        if existing:
            await message.answer("Usuário já é administrador.")
            await state.clear()
            return

    await state.update_data(target_user_id=str(target_user.id))
    await state.set_state(AdminAdminsStates.WAITING_ADMIN_ROLE)
    text = "Escolha o papel do novo administrador:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [create_button("ADMIN", "admins:role:ADMIN")],
            [create_button("OWNER", "admins:role:OWNER")],
            [create_button("🔙 CANCELAR", "admins:main")],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(AdminAdminsStates.WAITING_ADMIN_ROLE, F.data.startswith("admins:role:"))
async def process_admin_role(callback: CallbackQuery, state: FSMContext):
    """Recebe papel e cria o AdminUser com permissões padrão."""
    role = callback.data.split(":")[-1]  # ADMIN ou OWNER
    data = await state.get_data()
    target_user_id = UUID(data["target_user_id"])

    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode adicionar administradores.", show_alert=True)
            await state.clear()
            return

        # Se for OWNER, atualiza também User.is_owner
        if role == "OWNER":
            target_user = (await session.execute(
                select(User).where(User.id == target_user_id)
            )).scalar_one_or_none()
            if target_user:
                target_user.is_owner = True
                target_user.is_admin = True

        new_admin = AdminUser(
            tenant_id=tenant.id,
            user_id=target_user_id,
            role=role,
            is_active=True,
            granted_at=datetime.now(timezone.utc),
            granted_by_user_id=current_user.id,
            # Permissões padrão para ADMIN: todas True; OWNER também.
            can_manage_finance=True,
            can_manage_stock=True,
            can_manage_users=True,
            can_manage_support=True,
            can_manage_settings=True,
            can_manage_broadcast=True,
            can_manage_withdrawals=True,
            can_manage_affiliates=True,
            can_manage_products=True,
            can_manage_payments=True,
        )
        session.add(new_admin)
        await session.commit()

    await state.clear()
    await callback.answer(f"Administrador adicionado com papel {role}.")
    await show_admins_main(callback, state)


# ----------------------------------------------------------------------
# REMOVER ADMINISTRADOR
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admins:remove_select")
async def remove_admin_select(callback: CallbackQuery, state: FSMContext):
    """Lista admins para remoção."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode remover administradores.", show_alert=True)
            return
        admins = await _list_admins(session, tenant.id)

    if not admins:
        await callback.answer("Nenhum administrador para remover.")
        return

    text = "Selecione o administrador para remover:"
    buttons = []
    for admin, usr in admins:
        # Evita remover o último dono
        if usr.is_owner:
            continue
        buttons.append([create_button(f"{usr.first_name or usr.username} (ID: {usr.telegram_id})", f"admins:remove_confirm:{admin.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admins:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admins:remove_confirm:"))
async def remove_admin_confirm(callback: CallbackQuery, state: FSMContext):
    """Remove (soft delete) o AdminUser selecionado."""
    admin_id = UUID(callback.data.split(":")[-1])
    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode remover administradores.", show_alert=True)
            return

        admin = (await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )).scalar_one_or_none()
        if admin:
            # Não permite remover se for o último owner
            owner_count = (await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.is_owner == True, User.deleted_at.is_(None))
            )).scalars().all()
            if len(owner_count) <= 1:
                await callback.answer("Não é permitido remover o último dono.", show_alert=True)
                return
            admin.soft_delete()
            await session.commit()
            await callback.answer("Administrador removido.")
        else:
            await callback.answer("Administrador não encontrado.")

    await show_admins_main(callback, state)


# ----------------------------------------------------------------------
# DEFINIR PROPRIETÁRIO
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admins:set_owner_select")
async def set_owner_select(callback: CallbackQuery, state: FSMContext):
    """Lista admins para definir como proprietário."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode transferir propriedade.", show_alert=True)
            return
        admins = await _list_admins(session, tenant.id)

    if not admins:
        await callback.answer("Nenhum administrador disponível.")
        return

    text = "Selecione o administrador para tornar proprietário:"
    buttons = []
    for admin, usr in admins:
        buttons.append([create_button(f"{usr.first_name or usr.username} (ID: {usr.telegram_id})", f"admins:set_owner:{admin.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admins:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admins:set_owner:"))
async def set_owner_confirm(callback: CallbackQuery, state: FSMContext):
    """Define o AdminUser selecionado como proprietário, removendo o atual se necessário."""
    admin_id = UUID(callback.data.split(":")[-1])
    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode transferir propriedade.", show_alert=True)
            return

        admin = (await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )).scalar_one_or_none()
        if admin:
            # Remove propriedade do dono atual
            current_owner = (await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.is_owner == True, User.deleted_at.is_(None))
            )).scalars().first()
            if current_owner:
                current_owner.is_owner = False

            # Define novo dono
            target_user = (await session.execute(
                select(User).where(User.id == admin.user_id)
            )).scalar_one_or_none()
            if target_user:
                target_user.is_owner = True

            # Atualiza papel no AdminUser
            admin.role = "OWNER"
            await session.commit()
            await callback.answer("Propriedade transferida.")
        else:
            await callback.answer("Administrador não encontrado.")

    await show_admins_main(callback, state)


# ----------------------------------------------------------------------
# PERMISSÕES INDIVIDUAIS
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admins:permissions_select")
async def permissions_select(callback: CallbackQuery, state: FSMContext):
    """Lista admins para selecionar e editar permissões."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode alterar permissões.", show_alert=True)
            return
        admins = await _list_admins(session, tenant.id)

    if not admins:
        await callback.answer("Nenhum administrador disponível.")
        return

    text = "Selecione o administrador para editar permissões:"
    buttons = []
    for admin, usr in admins:
        buttons.append([create_button(f"{usr.first_name or usr.username}", f"admins:permissions_edit:{admin.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admins:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admins:permissions_edit:"))
async def permissions_edit(callback: CallbackQuery, state: FSMContext):
    """Exibe permissões atuais e permite alternar."""
    admin_id = UUID(callback.data.split(":")[-1])
    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode alterar permissões.", show_alert=True)
            return

        admin = (await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )).scalar_one_or_none()
        if admin is None:
            await callback.answer("Administrador não encontrado.")
            return

        # Monta mensagem com permissões
        perm_lines = []
        for code, label in PERMISSION_LABELS.items():
            status = "✅" if getattr(admin, code) else "❌"
            perm_lines.append(f"{status} {label}")

        text = f"Permissões de {admin.role}:\n\n" + "\n".join(perm_lines) + "\n\nClique em uma permissão para alternar:"

        buttons = []
        for code, label in PERMISSION_LABELS.items():
            buttons.append([create_button(f"{'✅' if getattr(admin, code) else '❌'} {label}", f"admins:toggle_perm:{admin.id}:{code}")])
        buttons.append([create_button("🔙 VOLTAR", "admins:permissions_select")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admins:toggle_perm:"))
async def toggle_permission(callback: CallbackQuery, state: FSMContext):
    """Alterna uma permissão específica."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Dados inválidos.")
        return
    admin_id = UUID(parts[2])
    perm_code = parts[3]

    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode alterar permissões.", show_alert=True)
            return

        admin = (await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )).scalar_one_or_none()
        if admin:
            current_val = getattr(admin, perm_code, False)
            setattr(admin, perm_code, not current_val)
            await session.commit()
            await callback.answer("Permissão atualizada.")
        else:
            await callback.answer("Administrador não encontrado.")

    await permissions_edit(callback, state)


# ----------------------------------------------------------------------
# BLOQUEAR/DESBLOQUEAR ADMINISTRADOR
# ----------------------------------------------------------------------

@router.callback_query(F.data == "admins:toggle_block_select")
async def toggle_block_select(callback: CallbackQuery, state: FSMContext):
    """Lista admins para bloquear/desbloquear."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode bloquear administradores.", show_alert=True)
            return
        admins = await _list_admins(session, tenant.id)

    if not admins:
        await callback.answer("Nenhum administrador disponível.")
        return

    text = "Selecione o administrador para bloquear/desbloquear:"
    buttons = []
    for admin, usr in admins:
        status = "🚫" if not admin.is_active else "✅"
        buttons.append([create_button(f"{status} {usr.first_name or usr.username}", f"admins:toggle_block:{admin.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admins:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admins:toggle_block:"))
async def toggle_block_admin(callback: CallbackQuery, state: FSMContext):
    """Alterna status de bloqueio do admin."""
    admin_id = UUID(callback.data.split(":")[-1])
    tenant, current_user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, current_user.id):
            await callback.answer("Apenas o proprietário pode bloquear administradores.", show_alert=True)
            return

        admin = (await session.execute(
            select(AdminUser).where(AdminUser.id == admin_id)
        )).scalar_one_or_none()
        if admin:
            # Não permite bloquear o último dono
            if admin.role == "OWNER":
                owner_count = (await session.execute(
                    select(User).where(User.tenant_id == tenant.id, User.is_owner == True, User.deleted_at.is_(None))
                )).scalars().all()
                if len(owner_count) <= 1:
                    await callback.answer("Não é permitido bloquear o último dono.", show_alert=True)
                    return
            admin.is_active = not admin.is_active
            await session.commit()
            await callback.answer(f"Administrador {'bloqueado' if not admin.is_active else 'desbloqueado'}.")
        else:
            await callback.answer("Administrador não encontrado.")

    await toggle_block_select(callback, state)
