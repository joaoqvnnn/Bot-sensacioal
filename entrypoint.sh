#!/bin/sh
set -e

echo "Aguardando banco de dados..."

python - <<PY
import asyncio
from bot.core.database import get_async_engine, Base
from bot.models import *

async def wait_for_db():
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(wait_for_db())
print("Banco OK")
PY

# Cria tenant se não existir
python - <<PY
import asyncio
from sqlalchemy import select
from bot.core.database import get_async_session_factory
from bot.models.tenant import Tenant

async def create_tenant():
    async with get_async_session_factory() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.slug == 'loja_teste')
        )).scalar_one_or_none()
        if not tenant:
            session.add(Tenant(name='Loja Teste', slug='loja_teste', plan='basic', is_active=True))
            await session.commit()
            print('Tenant criado')
        else:
            print('Tenant já existe')

asyncio.run(create_tenant())
PY

# Cria admin/dono se não existir
python - <<PY
import asyncio
import os
from sqlalchemy import select
from bot.core.database import get_async_session_factory
from bot.models.user import User
from bot.models.tenant import Tenant

async def create_admin():
    owner_id = int(os.getenv('TELEGRAM_OWNER_ID', '0'))
    if owner_id == 0:
        print('TELEGRAM_OWNER_ID não definido')
        return
    async with get_async_session_factory() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.slug == 'loja_teste')
        )).scalar_one_or_none()
        if not tenant:
            print('Tenant não encontrado')
            return
        user = (await session.execute(
            select(User).where(User.tenant_id == tenant.id, User.telegram_id == owner_id)
        )).scalar_one_or_none()
        if not user:
            user = User(
                tenant_id=tenant.id,
                telegram_id=owner_id,
                is_owner=True,
                is_admin=True,
                registered_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc)
            )
            session.add(user)
            await session.commit()
            print('Admin criado')
        else:
            user.is_owner = True
            user.is_admin = True
            await session.commit()
            print('Admin atualizado')

asyncio.run(create_admin())
PY

exec "$@"
