"""
Handlers administrativos de Categorias.

Seção 10 do painel: gerencia categorias de produtos.
Permite criar, editar, excluir, listar, reordenar e alterar visibilidade.
Tudo persistido na tabela Category.
"""

import logging
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.category import Category
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminCategoryStates(StatesGroup):
    WAITING_NAME = State()
    WAITING_EMOJI = State()
    WAITING_IMAGE = State()
    WAITING_POSITION = State()


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


async def _get_categories(session, tenant_id: UUID):
    """Lista categorias do tenant, ordenadas por posição."""
    stmt = select(Category).where(
        Category.tenant_id == tenant_id,
        Category.deleted_at.is_(None),
    ).order_by(Category.position.asc(), Category.name.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.callback_query(F.data == "categories:main")
async def categories_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de categorias."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        categories = await _get_categories(session, tenant.id)

    if not categories:
        text = "🛍️ CATEGORIAS\n\nNenhuma categoria cadastrada."
    else:
        text = "🛍️ CATEGORIAS\n\nCategorias:\n"
        for cat in categories:
            status = "🟢" if cat.is_active else "🔴"
            text += f"{status} {cat.emoji or ''} {cat.name} (posição: {cat.position})\n"

    text += "\nEscolha uma ação:"

    buttons = [
        [create_button("➕ Criar categoria", "categories:create")],
        [create_button("✏️ Editar categoria", "categories:edit_select")],
        [create_button("🗑 Excluir categoria", "categories:delete_select")],
        [create_button("Ativar/Desativar", "categories:toggle_select")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "categories:create")
async def category_create_start(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de categoria."""
    await state.set_state(AdminCategoryStates.WAITING_NAME)
    text = "Digite o nome da nova categoria:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "categories:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminCategoryStates.WAITING_NAME)
async def process_category_name(message: Message, state: FSMContext):
    """Recebe nome e pede emoji."""
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Nome inválido.")
        return

    await state.update_data(category_name=name)
    await state.set_state(AdminCategoryStates.WAITING_EMOJI)
    await message.answer("Envie um emoji para a categoria (ou '-' para sem emoji):")


@router.message(AdminCategoryStates.WAITING_EMOJI)
async def process_category_emoji(message: Message, state: FSMContext):
    """Recebe emoji e pede imagem (URL ou '-' para sem)."""
    emoji = message.text.strip() if message.text else ""
    if emoji == "-":
        emoji = None

    await state.update_data(category_emoji=emoji)
    await state.set_state(AdminCategoryStates.WAITING_IMAGE)
    await message.answer("Envie a URL da imagem da categoria (ou '-' para sem imagem):")


@router.message(AdminCategoryStates.WAITING_IMAGE)
async def process_category_image(message: Message, state: FSMContext):
    """Recebe imagem e finaliza criação."""
    image_url = message.text.strip() if message.text else ""
    if image_url == "-":
        image_url = None

    data = await state.get_data()
    name = data["category_name"]
    emoji = data.get("category_emoji")

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

        # Define posição como última + 1
        max_position = (await session.execute(
            select(func.max(Category.position)).where(Category.tenant_id == tenant.id)
        )).scalar() or 0

        category = Category(
            tenant_id=tenant.id,
            name=name,
            emoji=emoji,
            image_url=image_url,
            position=max_position + 1,
            is_active=True,
        )
        session.add(category)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Categoria '{name}' criada com sucesso!")


@router.callback_query(F.data == "categories:edit_select")
async def category_edit_select(callback: CallbackQuery, state: FSMContext):
    """Lista categorias para selecionar e editar."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        categories = await _get_categories(session, tenant.id)

    if not categories:
        await callback.answer("Nenhuma categoria cadastrada.")
        return

    text = "Selecione a categoria para editar:"
    buttons = []
    for cat in categories:
        buttons.append([create_button(f"{cat.emoji or ''} {cat.name}", f"categories:edit_name:{cat.id}")])
    buttons.append([create_button("🔙 VOLTAR", "categories:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("categories:edit_name:"))
async def category_edit_name(callback: CallbackQuery, state: FSMContext):
    """Pede novo nome para a categoria."""
    cat_id = UUID(callback.data.split(":")[-1])
    await state.update_data(edit_category_id=str(cat_id))
    await state.set_state(AdminCategoryStates.WAITING_NAME)
    text = "Digite o novo nome da categoria:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "categories:edit_select")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminCategoryStates.WAITING_NAME)
async def process_edit_category_name(message: Message, state: FSMContext):
    """Salva novo nome da categoria."""
    new_name = message.text.strip() if message.text else ""
    if not new_name:
        await message.answer("Nome inválido.")
        return

    data = await state.get_data()
    cat_id = UUID(data.get("edit_category_id"))

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

        category = (await session.execute(
            select(Category).where(Category.id == cat_id, Category.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if category:
            category.name = new_name
            await session.commit()
            await message.answer("✅ Nome da categoria atualizado.")
        else:
            await message.answer("Categoria não encontrada.")

    await state.clear()


@router.callback_query(F.data == "categories:delete_select")
async def category_delete_select(callback: CallbackQuery, state: FSMContext):
    """Lista categorias para exclusão."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        categories = await _get_categories(session, tenant.id)

    if not categories:
        await callback.answer("Nenhuma categoria cadastrada.")
        return

    text = "Selecione a categoria para excluir:"
    buttons = []
    for cat in categories:
        buttons.append([create_button(f"{cat.emoji or ''} {cat.name}", f"categories:delete_confirm:{cat.id}")])
    buttons.append([create_button("🔙 VOLTAR", "categories:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("categories:delete_confirm:"))
async def category_delete_confirm(callback: CallbackQuery, state: FSMContext):
    """Exclui categoria selecionada (soft delete)."""
    cat_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        category = (await session.execute(
            select(Category).where(Category.id == cat_id, Category.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if category:
            category.soft_delete()
            await session.commit()
            await callback.answer(f"Categoria '{category.name}' excluída.")
        else:
            await callback.answer("Categoria não encontrada.")

    await categories_main(callback, state)


@router.callback_query(F.data == "categories:toggle_select")
async def category_toggle_select(callback: CallbackQuery, state: FSMContext):
    """Lista categorias para alternar status."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        categories = await _get_categories(session, tenant.id)

    if not categories:
        await callback.answer("Nenhuma categoria cadastrada.")
        return

    text = "Selecione a categoria para alternar status:"
    buttons = []
    for cat in categories:
        status = "🟢" if cat.is_active else "🔴"
        buttons.append([create_button(f"{status} {cat.name}", f"categories:toggle:{cat.id}")])
    buttons.append([create_button("🔙 VOLTAR", "categories:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("categories:toggle:"))
async def category_toggle(callback: CallbackQuery, state: FSMContext):
    """Alterna status ativo/inativo da categoria."""
    cat_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        category = (await session.execute(
            select(Category).where(Category.id == cat_id, Category.tenant_id == tenant.id)
        )).scalar_one_or_none()
        if category:
            category.is_active = not category.is_active
            await session.commit()
            await callback.answer(f"Categoria '{category.name}' {'ativada' if category.is_active else 'desativada'}.")
        else:
            await callback.answer("Categoria não encontrada.")

    await category_toggle_select(callback, state)
