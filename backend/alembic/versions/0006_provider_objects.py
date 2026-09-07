"""Create provider_objects registry table

A1.7: Unified registry mapping cases to all external Razorpay provider objects
(orders, payment links, payments, invoices) with exact paise amounts and fees.

Revision ID: 0006_provider_objects
Revises: 0005_idempotency_and_provider_events
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006_provider_objects'
down_revision: Union[str, None] = '0005_idempotency_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_objects',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('case_id', sa.String(length=36), sa.ForeignKey('revenue_risk_cases.id'), nullable=True),
        sa.Column('object_type', sa.String(length=50), nullable=False),
        sa.Column('provider_object_id', sa.String(length=255), nullable=False),
        sa.Column('amount_paise', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('fee_paise', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_provider_objects_id', 'provider_objects', ['id'], unique=False)
    op.create_index('ix_provider_objects_case_id', 'provider_objects', ['case_id'], unique=False)
    op.create_index('ix_provider_objects_provider_object_id', 'provider_objects', ['provider_object_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_provider_objects_provider_object_id', table_name='provider_objects')
    op.drop_index('ix_provider_objects_case_id', table_name='provider_objects')
    op.drop_index('ix_provider_objects_id', table_name='provider_objects')
    op.drop_table('provider_objects')
