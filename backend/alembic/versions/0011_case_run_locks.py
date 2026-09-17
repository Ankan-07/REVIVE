"""Add case_run_locks table

Phase B4.3: Per-case execution registry and concurrency control.
Prevents race conditions between webhooks, operator resolve actions,
and background workers.

Revision ID: 0011_case_run_locks
Revises: 0010_gateway_fee_outcome
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011_case_run_locks'
down_revision: Union[str, None] = '0010_gateway_fee_outcome'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_run_locks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False, server_default='released'),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('locked_by_job_id', sa.String(length=64), nullable=True),
        sa.Column('lock_token', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_case_run_locks_id'), 'case_run_locks', ['id'], unique=False)
    op.create_index(op.f('ix_case_run_locks_case_id'), 'case_run_locks', ['case_id'], unique=True)
    op.create_index(op.f('ix_case_run_locks_state'), 'case_run_locks', ['state'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_case_run_locks_state'), table_name='case_run_locks')
    op.drop_index(op.f('ix_case_run_locks_case_id'), table_name='case_run_locks')
    op.drop_index(op.f('ix_case_run_locks_id'), table_name='case_run_locks')
    op.drop_table('case_run_locks')
