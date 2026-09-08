"""create whatsapp_messages table

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08 00:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Garante que a extensão uuid-ossp esteja disponível
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        'whatsapp_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('phone_number', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='SENT'),
        sa.Column('external_message_id', sa.String(100), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_whatsapp_messages_tenant_id', 'whatsapp_messages', ['tenant_id'])
    op.create_index('ix_whatsapp_messages_user_id', 'whatsapp_messages', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_whatsapp_messages_user_id', table_name='whatsapp_messages')
    op.drop_index('ix_whatsapp_messages_tenant_id', table_name='whatsapp_messages')
    op.drop_table('whatsapp_messages')
