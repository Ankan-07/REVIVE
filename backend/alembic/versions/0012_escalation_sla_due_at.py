"""Add sla_due_at to escalations table

Phase E1.2: Escalation SLA & aging alerts. Tracks when an unassigned
escalation breaches policy response time.

Revision ID: 0012_escalation_sla_due_at
Revises: 0011_case_run_locks
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012_escalation_sla_due_at'
down_revision: Union[str, None] = '0011_case_run_locks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('escalations', sa.Column('sla_due_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_escalations_sla_due_at'), 'escalations', ['sla_due_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_escalations_sla_due_at'), table_name='escalations')
    op.drop_column('escalations', 'sla_due_at')
