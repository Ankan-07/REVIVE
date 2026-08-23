"""0003_case_payment_link

Links a RevenueRiskCase to the failed payment it was opened for, and stores the initial
recovery-probability estimate computed at detection time:
  - revenue_risk_cases.payment_id            (FK -> payments.id; the case's dedup key + Phase-4 link)
  - revenue_risk_cases.recovery_probability  (best-of retry/switch/link §28 estimate at detection)

Revision ID: 0003_case_payment_link
Revises: 0002_sim_signals
Create Date: 2026-08-24 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_case_payment_link'
down_revision: Union[str, None] = '0002_sim_signals'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode = SQLite-safe (recreates the table) and Postgres-portable.
    with op.batch_alter_table('revenue_risk_cases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('recovery_probability', sa.Float(), nullable=True))
        batch_op.create_index(batch_op.f('ix_revenue_risk_cases_payment_id'), ['payment_id'], unique=False)
        batch_op.create_foreign_key('fk_revenue_risk_cases_payment_id_payments', 'payments', ['payment_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('revenue_risk_cases', schema=None) as batch_op:
        batch_op.drop_constraint('fk_revenue_risk_cases_payment_id_payments', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_revenue_risk_cases_payment_id'))
        batch_op.drop_column('recovery_probability')
        batch_op.drop_column('payment_id')
