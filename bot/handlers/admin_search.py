"""
Handlers administrativos de Pesquisa de Serviços.

Seção 22 do painel: gerencia configurações da pesquisa inline.
Permite ativar/desativar, definir limite de resultados, mínimo de caracteres,
produtos pesquisáveis, sinônimos e imagens.
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


class AdminSearchStates(StatesGroup):
    WAITING_VALUE = State()


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


@router.callback_query(F.data == "search_admin:main")
async def search_admin_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração da pesquisa."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        search_enabled = await _get_setting(session, tenant.id, "search_enabled") or "true"
        inline_mode = await _get_setting(session, tenant.id, "search_inline_mode") or "true"
        max_results = await _get_setting(session, tenant.id, "search_max_results") or "10"
        min_chars = await _get_setting(session, tenant.id, "search_min_chars") or "2"
        searchable_products = await _get_setting(session, tenant.id, "searchable_products") or "all"
        synonyms = await _get_setting(session, tenant.id, "search_synonyms") or "{}"
        images_enabled = await _get_setting(session, tenant.id, "search_images_enabled") or "true"

    text = (
        "🔎 PESQUISA DE SERVIÇOS\n\n"
        f"Status: {'🟢 ON' if search_enabled == 'true' else '🔴 OFF'}\n"
        f"Modo inline: {'Sim' if inline_mode == 'true' else 'Não'}\n"
        f"Máx. resultados: <b>{max_results}</b>\n"
        f"Mín. caracteres: <b>{min_chars}</b>\n"
        f"Produtos pesquisáveis: <b>{searchable_products}</b>\n"
        f"Sinônimos: <b>{synonyms[:50]}{'...' if len(synonyms) > 50 else ''}</b>\n"
        f"Imagens: {'Sim' if images_enabled == 'true' else 'Não'}\n\n"
        "Escolha uma opção:"
    )
    buttons = [
        [create_button("Ativar/Desativar pesquisa", "search_admin:toggle")],
        [create_button("Modo inline", "search_admin:toggle_inline")],
        [create_button("Alterar máx. resultados", "search_admin:set_max_results")],
        [create_button("Alterar mín. caracteres", "search_admin:set_min_chars")],
        [create_button("Produtos pesquisáveis", "search_admin:set_products")],
        [create_button("Sinônimos", "search_admin:set_synonyms")],
        [create_button("Imagens", "search_admin:toggle_images")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "search_admin:toggle")
async def toggle_search(callback: CallbackQuery, state: FSMContext):
    """Alterna status da pesquisa."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "search_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "search_enabled", new_val)

    await callback.answer(f"Pesquisa {'ativada' if new_val == 'true' else 'desativada'}.")
    await search_admin_main(callback, state)


@router.callback_query(F.data == "search_admin:toggle_inline")
async def toggle_inline(callback: CallbackQuery, state: FSMContext):
    """Alterna modo inline."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "search_inline_mode") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "search_inline_mode", new_val)

    await callback.answer(f"Modo inline {'ativado' if new_val == 'true' else 'desativado'}.")
    await search_admin_main(callback, state)


@router.callback_query(F.data == "search_admin:toggle_images")
async def toggle_images(callback: CallbackQuery, state: FSMContext):
    """Alterna exibição de imagens na pesquisa."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        current = await _get_setting(session, tenant.id, "search_images_enabled") or "true"
        new_val = "false" if current == "true" else "true"
        await _set_setting(session, tenant.id, "search_images_enabled", new_val)

    await callback.answer(f"Imagens {'ativadas' if new_val == 'true' else 'desativadas'}.")
    await search_admin_main(callback, state)


async def _edit_search_setting(callback: CallbackQuery, state: FSMContext, key: str, title: str):
    """Inicia edição de configuração da pesquisa."""
    await state.set_state(AdminSearchStates.WAITING_VALUE)
    await state.update_data(search_setting_key=key)
    text = f"Digite o novo valor para <b>{title}</b>:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "search_admin:main")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "search_admin:set_max_results")
async def set_max_results(callback: CallbackQuery, state: FSMContext):
    await _edit_search_setting(callback, state, "search_max_results", "máximo de resultados")


@router.callback_query(F.data == "search_admin:set_min_chars")
async def set_min_chars(callback: CallbackQuery, state: FSMContext):
    await _edit_search_setting(callback, state, "search_min_chars", "mínimo de caracteres")


@router.callback_query(F.data == "search_admin:set_products")
async def set_products(callback: CallbackQuery, state: FSMContext):
    await _edit_search_setting(callback, state, "searchable_products", "produtos pesquisáveis (all ou lista de IDs)")


@router.callback_query(F.data == "search_admin:set_synonyms")
async def set_synonyms(callback: CallbackQuery, state: FSMContext):
    await _edit_search_setting(callback, state, "search_synonyms", "sinônimos (JSON)")


@router.message(AdminSearchStates.WAITING_VALUE)
async def process_search_setting(message: Message, state: FSMContext):
    """Salva novo valor da configuração da pesquisa."""
    new_value = message.text.strip()
    if not new_value:
        await message.answer("Valor vazio não permitido.")
        return

    data = await state.get_data()
    setting_key = data.get("search_setting_key")

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
    await message.answer("✅ Configuração de pesquisa atualizada.")
