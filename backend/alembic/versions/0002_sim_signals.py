"""0002_sim_signals

Adds the PRD §28 payment-simulation ground-truth signals and gateway baseline:
  - customers.intent_score          (customer_intent)
  - payments.order_id               (payment -> order link)
  - payments.method_health          (payment-instrument health)
  - payments.recovery_roll          (stored uniform draw for deterministic outcomes)
  - gateway_metrics.baseline_success_rate  (current vs baseline for diagnosis)

Revision ID: 0002_sim_signals
Revises: 0001_initial
Create Date: 2026-08-24 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002_sim_signals'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('intent_score', sa.Float(), nullable=True))
    op.add_column('gateway_metrics', sa.Column('baseline_success_rate', sa.Float(), nullable=True))

    # Batch mode = SQLite-safe (recreates the table) and Postgres-portable.
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('order_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('method_health', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('recovery_roll', sa.Float(), nullable=True))
        batch_op.create_index(batch_op.f('ix_payments_order_id'), ['order_id'], unique=False)
        batch_op.create_foreign_key('fk_payments_order_id_orders', 'orders', ['order_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_payments_order_id_orders', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_payments_order_id'))
        batch_op.drop_column('recovery_roll')
        batch_op.drop_column('method_health')
        batch_op.drop_column('order_id')

    op.drop_column('gateway_metrics', 'baseline_success_rate')
    op.drop_column('customers', 'intent_score')
