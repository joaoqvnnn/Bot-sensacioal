"""
Handlers administrativos de Configuração dos Botões.

Permite ao administrador gerenciar os layouts de teclados inline:
- Listar layouts existentes (home, catálogo, produto, perfil, etc.)
- Criar novo layout com JSON de botões
- Editar layout (texto, emoji, callback, URL, ordem, posição, row_width)
- Excluir layout
- Ativar/desativar layout (controla se será usado)

Os layouts são armazenados na tabela KeyboardLayout (code, buttons_json, row_width).
O backend lê esses layouts ao montar os teclados das telas.
"""

import json
import logging
from typing import Optional, List
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.core.database import get_async_session_factory
from bot.keyboards.utils import create_button
from bot.models.keyboard_layout import KeyboardLayout
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


class AdminButtonsStates(StatesGroup):
    WAITING_LAYOUT_CODE = State()
    WAITING_BUTTONS_JSON = State()
    WAITING_ROW_WIDTH = State()


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


async def _get_layouts(session, tenant_id: UUID) -> List[KeyboardLayout]:
    """Lista layouts de teclado do tenant."""
    stmt = select(KeyboardLayout).where(
        KeyboardLayout.tenant_id == tenant_id,
        KeyboardLayout.deleted_at.is_(None),
    ).order_by(KeyboardLayout.code)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.callback_query(F.data == "admin:buttons")
async def show_buttons_menu(callback: CallbackQuery, state: FSMContext):
    """Menu principal de configuração de botões."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        text = "🔘 CONFIGURAÇÃO DOS BOTÕES\n\nNenhum layout cadastrado."
    else:
        text = "🔘 CONFIGURAÇÃO DOS BOTÕES\n\nLayouts disponíveis:\n"
        for layout in layouts:
            status = "🟢" if layout.is_active else "🔴"
            text += f"{status} <b>{layout.code}</b> (row_width: {layout.row_width})\n"

    buttons = [
        [create_button("➕ Criar layout", "admin:buttons:create")],
        [create_button("✏️ Editar layout", "admin:buttons:edit_select")],
        [create_button("🗑 Excluir layout", "admin:buttons:delete_select")],
        [create_button("Ativar/Desativar", "admin:buttons:toggle_select")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "admin:buttons:create")
async def create_layout_start(callback: CallbackQuery, state: FSMContext):
    """Inicia criação de novo layout."""
    await state.set_state(AdminButtonsStates.WAITING_LAYOUT_CODE)
    text = "Digite o código do novo layout (ex: main_menu, catalog, product):"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:buttons")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_LAYOUT_CODE)
async def process_layout_code(message: Message, state: FSMContext):
    """Recebe código e pede JSON de botões."""
    code = message.text.strip().lower()
    if not code:
        await message.answer("Código inválido.")
        return

    tenant, user = await _get_tenant_and_user_from_message(message)
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
            select(KeyboardLayout).where(
                KeyboardLayout.tenant_id == tenant.id,
                KeyboardLayout.code == code,
                KeyboardLayout.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if existing:
            await message.answer("Já existe layout com esse código.")
            await state.clear()
            return

    await state.update_data(layout_code=code)
    await state.set_state(AdminButtonsStates.WAITING_BUTTONS_JSON)
    await message.answer(
        "Agora envie o JSON dos botões.\n\n"
        "Exemplo de formato:\n"
        '{"buttons": [{"text": "🛍 Comprar Produtos", "callback": "menu:catalog"}], "row_width": 2}\n\n'
        "Você pode incluir botões com 'url' em vez de 'callback'. "
        "Cada botão deve ter 'text' e 'callback' ou 'url'."
    )


@router.message(AdminButtonsStates.WAITING_BUTTONS_JSON)
async def process_buttons_json(message: Message, state: FSMContext):
    """Recebe JSON e pede row_width se necessário."""
    try:
        data = json.loads(message.text.strip())
        buttons = data.get("buttons", [])
        row_width = data.get("row_width", 2)
        if not isinstance(buttons, list) or not isinstance(row_width, int) or row_width < 1:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        await message.answer(
            "JSON inválido. Certifique-se de que segue o formato esperado."
        )
        return

    await state.update_data(buttons_json=buttons, row_width=row_width)
    # Finaliza criação sem pedir row_width separado, pois já está no JSON
    await _save_layout(message, state, create=True)


async def _save_layout(message: Message, state: FSMContext, create: bool):
    """Salva o layout no banco."""
    data = await state.get_data()
    code = data.get("layout_code")
    buttons = data.get("buttons_json")
    row_width = data.get("row_width", 2)

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

        if create:
            layout = KeyboardLayout(
                tenant_id=tenant.id,
                code=code,
                buttons_json=json.dumps(buttons, ensure_ascii=False),
                row_width=row_width,
            )
            session.add(layout)
            await session.commit()
            await message.answer(f"✅ Layout '{code}' criado com sucesso!")
        else:
            # Edição (será implementada em fluxo separado)
            pass

    await state.clear()


@router.callback_query(F.data == "admin:buttons:edit_select")
async def edit_layout_select(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para selecionar e editar."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para editar:"
    buttons = []
    for layout in layouts:
        buttons.append([create_button(layout.code, f"admin:buttons:edit:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admin:buttons:edit:"))
async def edit_layout_start(callback: CallbackQuery, state: FSMContext):
    """Pede novo JSON para o layout selecionado."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = (await session.execute(
            select(KeyboardLayout).where(KeyboardLayout.id == layout_id)
        )).scalar_one_or_none()
        if layout is None:
            await callback.answer("Layout não encontrado.")
            return

    await state.update_data(edit_layout_id=str(layout.id), edit_layout_code=layout.code)
    await state.set_state(AdminButtonsStates.WAITING_BUTTONS_JSON)
    text = (
        f"Editando layout <b>{layout.code}</b>\n"
        f"JSON atual: <code>{layout.buttons_json}</code>\n\n"
        "Envie o novo JSON dos botões no mesmo formato."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[create_button("🔙 CANCELAR", "admin:buttons")]]
    )
    await _edit_or_answer(callback, text, keyboard)


@router.message(AdminButtonsStates.WAITING_BUTTONS_JSON)
async def process_edit_buttons_json(message: Message, state: FSMContext):
    """Recebe JSON de edição e salva."""
    try:
        data = json.loads(message.text.strip())
        buttons = data.get("buttons", [])
        row_width = data.get("row_width", 2)
        if not isinstance(buttons, list) or not isinstance(row_width, int) or row_width < 1:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        await message.answer("JSON inválido.")
        return

    layout_id = UUID(data.get("edit_layout_id"))
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

        layout = (await session.execute(
            select(KeyboardLayout).where(KeyboardLayout.id == layout_id)
        )).scalar_one_or_none()
        if layout:
            layout.buttons_json = json.dumps(buttons, ensure_ascii=False)
            layout.row_width = row_width
            await session.commit()
            await message.answer("✅ Layout atualizado!")

    await state.clear()


@router.callback_query(F.data == "admin:buttons:delete_select")
async def delete_layout_select(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para exclusão."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para excluir:"
    buttons = []
    for layout in layouts:
        buttons.append([create_button(layout.code, f"admin:buttons:delete:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admin:buttons:delete:"))
async def delete_layout(callback: CallbackQuery, state: FSMContext):
    """Exclui layout selecionado (soft delete)."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = (await session.execute(
            select(KeyboardLayout).where(KeyboardLayout.id == layout_id)
        )).scalar_one_or_none()
        if layout:
            layout.soft_delete()
            await session.commit()
            await callback.answer(f"Layout '{layout.code}' excluído.")
        else:
            await callback.answer("Layout não encontrado.")

    await show_buttons_menu(callback, state)


@router.callback_query(F.data == "admin:buttons:toggle_select")
async def toggle_layout_select(callback: CallbackQuery, state: FSMContext):
    """Lista layouts para alternar status."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return
        layouts = await _get_layouts(session, tenant.id)

    if not layouts:
        await callback.answer("Nenhum layout cadastrado.")
        return

    text = "Selecione o layout para alternar:"
    buttons = []
    for layout in layouts:
        status = "🟢" if layout.is_active else "🔴"
        buttons.append([create_button(f"{status} {layout.code}", f"admin:buttons:toggle:{layout.id}")])
    buttons.append([create_button("🔙 VOLTAR", "admin:buttons")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data.startswith("admin:buttons:toggle:"))
async def toggle_layout(callback: CallbackQuery, state: FSMContext):
    """Alterna status ativo/inativo do layout."""
    layout_id = UUID(callback.data.split(":")[-1])
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        layout = (await session.execute(
            select(KeyboardLayout).where(KeyboardLayout.id == layout_id)
        )).scalar_one_or_none()
        if layout:
            layout.is_active = not layout.is_active
            await session.commit()
            await callback.answer(f"Layout '{layout.code}' {'ativado' if layout.is_active else 'desativado'}.")
        else:
            await callback.answer("Layout não encontrado.")

    await toggle_layout_select(callback, state)
