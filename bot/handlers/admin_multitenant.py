"""
Handlers administrativos de Multi-tenant / Aluguel.

Seção 29 do painel: gerencia tenants (clientes que alugam bots).
Permite listar, criar, editar plano/vencimento/VIP e ativar/desativar.

Apenas o proprietário (owner) pode gerenciar tenants.
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
from bot.core.utils import cents_to_brl
from bot.keyboards.utils import create_button
from bot.models.tenant import Tenant
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminMTStates(StatesGroup):
    WAITING_NAME = State()
    WAITING_SLUG = State()
    WAITING_PLAN = State()
    WAITING_EXPIRES_DAYS = State()
    WAITING_EDIT_PLAN = State()
    WAITING_EDIT_EXPIRES_DAYS = State()


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


async def _is_owner(session, tenant_id: UUID, user_id: UUID) -> bool:
    """Verifica se o usuário é dono do tenant."""
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


@router.callback_query(F.data == "mt:main")
async def mt_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de multi-tenant."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode gerenciar tenants.", show_alert=True)
            return

        tenants = (await session.execute(
            select(Tenant)
            .where(Tenant.deleted_at.is_(None))
            .order_by(Tenant.created_at.asc())
            .limit(10)
        )).scalars().all()

    if not tenants:
        text = "Nenhum tenant cadastrado."
    else:
        text = "🏢 Tenants:\n\n"
        for t in tenants:
            expires = t.expires_at.strftime("%d/%m/%Y") if t.expires_at else "Sem vencimento"
            vip = "👑" if t.vip else ""
            text += f"• {t.name} ({t.slug}){vip} - Plano: {t.plan or 'N/A'} - Venc: {expires}\n"

    text += "\nEscolha uma opção:"
    buttons = [
        [create_button("➕ Criar tenant", "mt:create_start")],
        [create_button("✏️ Editar tenant", "mt:edit_select")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "mt:create_start")
async def mt_create_start(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de novo tenant."""
    await state.set_state(AdminMTStates.WAITING_NAME)
    text = "Digite o nome do novo tenant:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "mt:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminMTStates.WAITING_NAME)
async def process_mt_name(message: Message, state: FSMContext):
    """Recebe nome e pede slug."""
    name = message.text.strip()
    if not name:
        await message.answer("Nome inválido.")
        return

    await state.update_data(mt_name=name)
    await state.set_state(AdminMTStates.WAITING_SLUG)
    await message.answer("Digite o slug único (ex: loja1):")


@router.message(AdminMTStates.WAITING_SLUG)
async def process_mt_slug(message: Message, state: FSMContext):
    """Recebe slug e pede plano."""
    slug = message.text.strip().lower()
    if not slug or not slug.replace("-", "").isalnum():
        await message.answer("Slug inválido. Use apenas letras, números e hífen.")
        return

    await state.update_data(mt_slug=slug)
    await state.set_state(AdminMTStates.WAITING_PLAN)
    await message.answer("Digite o plano (ex: gold, silver, basic) ou '-' para sem plano:")


@router.message(AdminMTStates.WAITING_PLAN)
async def process_mt_plan(message: Message, state: FSMContext):
    """Recebe plano e pede dias de vencimento."""
    plan = message.text.strip()
    if plan == "-":
        plan = None

    await state.update_data(mt_plan=plan)
    await state.set_state(AdminMTStates.WAITING_EXPIRES_DAYS)
    await message.answer("Digite os dias até vencimento (ex: 365):")


@router.message(AdminMTStates.WAITING_EXPIRES_DAYS)
async def process_mt_expires(message: Message, state: FSMContext):
    """Recebe dias e cria tenant."""
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("Dias inválidos.")
        return

    data = await state.get_data()
    name = data["mt_name"]
    slug = data["mt_slug"]
    plan = data.get("mt_plan")

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await message.answer("Apenas o proprietário pode criar tenants.")
            await state.clear()
            return

        # Verifica duplicidade de slug
        existing = (await session.execute(
            select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
        )).scalar_one_or_none()
        if existing:
            await message.answer("Já existe tenant com esse slug.")
            await state.clear()
            return

        expires_at = datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None

        new_tenant = Tenant(
            name=name,
            slug=slug,
            plan=plan,
            vip=False,
            is_active=True,
            expires_at=expires_at,
        )
        session.add(new_tenant)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Tenant '{name}' criado com sucesso!")


@router.callback_query(F.data == "mt:edit_select")
async def mt_edit_select(callback: CallbackQuery, state: FSMContext):
    """Lista tenants para edição."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode editar tenants.", show_alert=True)
            return

        tenants = (await session.execute(
            select(Tenant).where(Tenant.deleted_at.is_(None))
        )).scalars().all()

    if not tenants:
        await callback.answer("Nenhum tenant.")
        return

    text = "Selecione o tenant para editar:"
    buttons = []
    for t in tenants:
        buttons.append([create_button(f"{t.name}", f"mt:edit_menu:{t.id}")])
    buttons.append([create_button("🔙 VOLTAR", "mt:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("mt:edit_menu:"))
async def mt_edit_menu(callback: CallbackQuery, state: FSMContext):
    """Menu de edição de um tenant."""
    tenant_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode editar tenants.", show_alert=True)
            return

        target = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if target is None:
            await callback.answer("Tenant não encontrado.")
            return

    await state.update_data(edit_tenant_id=str(target.id))

    text = (
        f"🏢 Editando: <b>{target.name}</b>\n"
        f"Slug: {target.slug}\n"
        f"Plano: {target.plan or 'N/A'}\n"
        f"VIP: {'Sim' if target.vip else 'Não'}\n"
        f"Vencimento: {target.expires_at.strftime('%d/%m/%Y') if target.expires_at else 'Sem'}\n"
        f"Ativo: {'Sim' if target.is_active else 'Não'}\n\n"
        "O que deseja alterar?"
    )
    buttons = [
        [create_button("Alterar plano", "mt:edit_plan")],
        [create_button("Alterar vencimento", "mt:edit_expires")],
        [create_button("Alternar VIP", "mt:toggle_vip")],
        [create_button("Ativar/Desativar", "mt:toggle_active")],
        [create_button("🔙 VOLTAR", "mt:edit_select")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "mt:edit_plan")
async def mt_edit_plan(callback: CallbackQuery, state: FSMContext):
    """Pede novo plano."""
    await state.set_state(AdminMTStates.WAITING_EDIT_PLAN)
    text = "Digite o novo plano (ou '-' para remover):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "mt:edit_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminMTStates.WAITING_EDIT_PLAN)
async def process_mt_edit_plan(message: Message, state: FSMContext):
    """Salva novo plano."""
    plan = message.text.strip()
    if plan == "-":
        plan = None

    data = await state.get_data()
    tenant_id = UUID(data["edit_tenant_id"])

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await message.answer("Apenas o proprietário pode editar.")
            await state.clear()
            return
        target = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if target:
            target.plan = plan
            await session.commit()
            await message.answer("✅ Plano atualizado.")
        else:
            await message.answer("Tenant não encontrado.")

    await state.clear()


@router.callback_query(F.data == "mt:edit_expires")
async def mt_edit_expires(callback: CallbackQuery, state: FSMContext):
    """Pede novos dias para vencimento."""
    await state.set_state(AdminMTStates.WAITING_EDIT_EXPIRES_DAYS)
    text = "Digite os dias até vencimento a partir de hoje (0 para sem vencimento):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "mt:edit_menu")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminMTStates.WAITING_EDIT_EXPIRES_DAYS)
async def process_mt_edit_expires(message: Message, state: FSMContext):
    """Salva novo vencimento."""
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("Dias inválidos.")
        return

    data = await state.get_data()
    tenant_id = UUID(data["edit_tenant_id"])

    tenant, user = await _get_tenant_and_user_from_message(message)
    if tenant is None:
        await message.answer("Sistema indisponível.")
        await state.clear()
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await message.answer("Apenas o proprietário pode editar.")
            await state.clear()
            return
        target = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if target:
            target.expires_at = datetime.now(timezone.utc) + timedelta(days=days) if days > 0 else None
            await session.commit()
            await message.answer("✅ Vencimento atualizado.")
        else:
            await message.answer("Tenant não encontrado.")

    await state.clear()


@router.callback_query(F.data == "mt:toggle_vip")
async def mt_toggle_vip(callback: CallbackQuery, state: FSMContext):
    """Alterna status VIP do tenant."""
    data = await state.get_data()
    tenant_id = UUID(data["edit_tenant_id"])

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode editar.", show_alert=True)
            return
        target = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if target:
            target.vip = not target.vip
            await session.commit()
            await callback.answer(f"VIP {'ativado' if target.vip else 'desativado'}.")
        else:
            await callback.answer("Tenant não encontrado.")

    await mt_edit_menu(callback, state)


@router.callback_query(F.data == "mt:toggle_active")
async def mt_toggle_active(callback: CallbackQuery, state: FSMContext):
    """Alterna status ativo/inativo do tenant."""
    data = await state.get_data()
    tenant_id = UUID(data["edit_tenant_id"])

    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_owner(session, tenant.id, user.id):
            await callback.answer("Apenas o proprietário pode editar.", show_alert=True)
            return
        target = (await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )).scalar_one_or_none()
        if target:
            target.is_active = not target.is_active
            await session.commit()
            await callback.answer(f"Tenant {'ativado' if target.is_active else 'desativado'}.")
        else:
            await callback.answer("Tenant não encontrado.")

    await mt_edit_menu(callback, state)
