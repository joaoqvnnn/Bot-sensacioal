"""
Handlers administrativos de Integridade do Sistema.

Seção 31 do painel: executa verificações reais de integridade.
Inclui:
- Imports principais
- Dependências instaladas
- Migrations aplicadas
- Tabelas existentes no banco
- Workers registrados
- Testes automatizados (se disponível)

Sem simulação: cada verificação consulta o estado real do sistema.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, inspect

from bot.core.database import get_async_session_factory, get_async_engine
from bot.keyboards.utils import create_button
from bot.models.user import User
from bot.services.user_service import get_tenant_for_bot, get_or_create_user

logger = logging.getLogger(__name__)

router = Router()


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


@router.callback_query(F.data == "integrity:main")
async def integrity_main(callback: CallbackQuery, state: FSMContext):
    """Menu principal de integridade do sistema."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    text = (
        "🧪 INTEGRIDADE DO SISTEMA\n\n"
        "Escolha uma verificação:\n"
    )
    buttons = [
        [create_button("Verificar imports", "integrity:imports")],
        [create_button("Verificar dependências", "integrity:deps")],
        [create_button("Verificar migrations", "integrity:migrations")],
        [create_button("Verificar tabelas", "integrity:tables")],
        [create_button("Verificar workers", "integrity:workers")],
        [create_button("Verificar webhooks", "integrity:webhooks")],
        [create_button("Testes automatizados", "integrity:tests")],
        [create_button("🔙 VOLTAR", "admin:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:imports")
async def check_imports(callback: CallbackQuery, state: FSMContext):
    """Verifica imports principais do bot."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    modules_to_check = [
        "bot.core.config",
        "bot.core.database",
        "bot.core.redis",
        "bot.core.security",
        "bot.models",
        "bot.handlers",
        "bot.services",
        "bot.workers.tasks",
    ]

    results = []
    for mod in modules_to_check:
        try:
            __import__(mod)
            results.append(f"✅ {mod}")
        except Exception as e:
            results.append(f"❌ {mod}: {e}")

    text = "Verificação de imports:\n\n" + "\n".join(results)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:deps")
async def check_deps(callback: CallbackQuery, state: FSMContext):
    """Verifica dependências instaladas (versões principais)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    deps = [
        "aiogram",
        "sqlalchemy",
        "asyncpg",
        "alembic",
        "redis",
        "pydantic",
        "httpx",
        "cryptography",
    ]

    results = []
    for dep in deps:
        try:
            mod = __import__(dep)
            version = getattr(mod, "__version__", "?")
            results.append(f"✅ {dep} {version}")
        except Exception:
            results.append(f"❌ {dep} não instalado")

    text = "Dependências:\n\n" + "\n".join(results)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:migrations")
async def check_migrations(callback: CallbackQuery, state: FSMContext):
    """Verifica status das migrations (via Alembic)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    result_lines = []
    try:
        from alembic import command
        from alembic.config import Config
        import io
        cfg = Config("alembic.ini")
        buf = io.StringIO()
        # current mostra a revisão atual
        command.current(cfg, stdout=buf)
        current = buf.getvalue().strip()
        result_lines.append(f"Revisão atual: {current or 'Nenhuma migration aplicada'}")
    except Exception as e:
        result_lines.append(f"❌ Erro ao verificar migrations: {e}")

    text = "Migrations:\n\n" + "\n".join(result_lines)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:tables")
async def check_tables(callback: CallbackQuery, state: FSMContext):
    """Verifica tabelas existentes no banco."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

        engine = get_async_engine()
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    expected_tables = [
        "tenants", "users", "admin_users", "wallets", "wallet_ledger",
        "categories", "products", "inventory_items", "orders", "order_items",
        "payments", "referrals", "affiliate_commissions", "affiliate_points",
        "affiliate_withdrawals", "withdrawal_accounts", "gift_cards",
        "gift_redemptions", "delivery_jobs", "delivery_attempts",
        "email_verifications", "whatsapp_verifications", "product_access_tokens",
        "support_tickets", "support_messages", "ai_sessions",
        "alerts_subscriptions", "broadcasts", "scheduled_notifications",
        "anti_flood_events", "user_blocks", "audit_logs", "settings",
        "message_templates", "keyboard_layouts", "media_assets", "webapp_sessions",
    ]

    results = []
    for table in expected_tables:
        if table in tables:
            results.append(f"✅ {table}")
        else:
            results.append(f"❌ {table} ausente")

    text = "Tabelas:\n\n" + "\n".join(results)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:workers")
async def check_workers(callback: CallbackQuery, state: FSMContext):
    """Verifica workers registrados no arq."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    try:
        from bot.workers.tasks import WorkerSettings
        functions = WorkerSettings.functions
        lines = [f"✅ {len(functions)} tarefa(s) registrada(s):"]
        for f in functions:
            lines.append(f"• {f.__name__}")
    except Exception as e:
        lines = [f"❌ Erro ao carregar workers: {e}"]

    text = "Workers:\n\n" + "\n".join(lines)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:webhooks")
async def check_webhooks(callback: CallbackQuery, state: FSMContext):
    """Verifica webhooks configurados (indicações)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    # Não há consulta direta; apenas informa configuração via .env/settings
    from bot.core.config import settings

    lines = []
    lines.append("Webhooks configurados:")
    if settings.TELEGRAM_WEBHOOK_URL:
        lines.append(f"✅ Telegram: {settings.TELEGRAM_WEBHOOK_URL}")
    else:
        lines.append("ℹ️ Telegram webhook não configurado (usando polling).")
    if settings.MERCADO_PAGO_NOTIFICATION_URL:
        lines.append(f"✅ Mercado Pago: {settings.MERCADO_PAGO_NOTIFICATION_URL}")
    else:
        lines.append("ℹ️ Mercado Pago webhook não configurado.")

    text = "\n".join(lines)
    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)


@router.callback_query(F.data == "integrity:tests")
async def run_tests(callback: CallbackQuery, state: FSMContext):
    """Executa testes automatizados (se pytest disponível)."""
    tenant, user = await _get_tenant_and_user_from_callback(callback)
    if tenant is None:
        await callback.answer("Sistema indisponível.")
        return

    async with get_async_session_factory() as session:
        if not await _is_admin(session, tenant.id, user.id):
            await callback.answer("Acesso negado.", show_alert=True)
            return

    try:
        import pytest
        # Executa testes em modo silencioso e coleta resultado
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: pytest.main(["-q", "--no-header", "--no-summary"]))
        text = f"Testes executados. Código de saída: {result}"
    except ImportError:
        text = "pytest não instalado. Não é possível executar testes."
    except Exception as e:
        text = f"Erro ao executar testes: {e}"

    buttons = [[create_button("🔙 VOLTAR", "integrity:main")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback, text, keyboard)
