"""Add idempotency_key to interventions and create provider_events table

A1.2: Adds first-class idempotency_key column on interventions with unique constraint
and data backfill from payload_json.
A1.3: Creates provider_events table with unique razorpay_event_id for webhook deduplication.

Revision ID: 0005_idempotency_events
Revises: 0004_outcome_discount_total
Create Date: 2026-09-06
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005_idempotency_events'
down_revision: Union[str, None] = '0004_outcome_discount_total'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add idempotency_key to interventions (nullable initially for backfill)
    with op.batch_alter_table('interventions') as batch_op:
        batch_op.add_column(
            sa.Column('idempotency_key', sa.String(length=255), nullable=True)
        )

    # 2. Data backfill from payload_json -> idempotency_key
    bind = op.get_bind()
    intervention_table = sa.table(
        'interventions',
        sa.column('id', sa.String),
        sa.column('payload_json', sa.JSON),
        sa.column('idempotency_key', sa.String),
    )
    
    # Fetch rows with payload_json
    select_stmt = sa.select(intervention_table.c.id, intervention_table.c.payload_json).where(
        intervention_table.c.payload_json.isnot(None)
    )
    results = bind.execute(select_stmt).fetchall()
    for row_id, payload in results:
        if not payload:
            continue
        # Handle dict or serialized JSON string
        data = json.loads(payload) if isinstance(payload, str) else payload
        if isinstance(data, dict) and "idempotency_key" in data:
            key = data["idempotency_key"]
            if key:
                bind.execute(
                    intervention_table.update()
                    .where(intervention_table.c.id == row_id)
                    .values(idempotency_key=str(key))
                )

    # 3. Create unique index on interventions(idempotency_key)
    with op.batch_alter_table('interventions') as batch_op:
        batch_op.create_index('ix_interventions_idempotency_key', ['idempotency_key'], unique=True)

    # 4. Create provider_events table for webhook deduplication (A1.3)
    op.create_table(
        'provider_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='razorpay'),
        sa.Column('razorpay_event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_provider_events_id', 'provider_events', ['id'], unique=False)
    op.create_index('ix_provider_events_razorpay_event_id', 'provider_events', ['razorpay_event_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_provider_events_razorpay_event_id', table_name='provider_events')
    op.drop_index('ix_provider_events_id', table_name='provider_events')
    op.drop_table('provider_events')

    with op.batch_alter_table('interventions') as batch_op:
        batch_op.drop_index('ix_interventions_idempotency_key')
        batch_op.drop_column('idempotency_key')
