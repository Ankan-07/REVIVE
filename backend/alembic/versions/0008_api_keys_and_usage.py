"""Add api_keys and key_usage_events tables

Phase A2.1: Creates api_keys table for per-person, scoped service API keys
and key_usage_events for rate-limit tracking and immutable usage auditing.

Revision ID: 0008_api_keys_and_usage
Revises: 0007_origin_timezone
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_api_keys_and_usage'
down_revision: Union[str, None] = '0007_origin_timezone'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create api_keys table
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=255), nullable=False),
        sa.Column('salt', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.String(length=255), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_keys_id', 'api_keys', ['id'], unique=False)
    op.create_index('ix_api_keys_name', 'api_keys', ['name'], unique=False)
    op.create_index('ix_api_keys_key_prefix', 'api_keys', ['key_prefix'], unique=True)
    op.create_index('ix_api_keys_revoked', 'api_keys', ['revoked'], unique=False)

    # 2. Create key_usage_events table
    op.create_table(
        'key_usage_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('key_id', sa.String(length=36), nullable=False),
        sa.Column('route', sa.String(length=255), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['key_id'], ['api_keys.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_key_usage_events_id', 'key_usage_events', ['id'], unique=False)
    op.create_index('ix_key_usage_events_key_id', 'key_usage_events', ['key_id'], unique=False)
    op.create_index('ix_key_usage_events_timestamp', 'key_usage_events', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_key_usage_events_timestamp', table_name='key_usage_events')
    op.drop_index('ix_key_usage_events_key_id', table_name='key_usage_events')
    op.drop_index('ix_key_usage_events_id', table_name='key_usage_events')
    op.drop_table('key_usage_events')

    op.drop_index('ix_api_keys_revoked', table_name='api_keys')
    op.drop_index('ix_api_keys_key_prefix', table_name='api_keys')
    op.drop_index('ix_api_keys_name', table_name='api_keys')
    op.drop_index('ix_api_keys_id', table_name='api_keys')
    op.drop_table('api_keys')
