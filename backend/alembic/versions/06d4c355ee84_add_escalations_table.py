"""Add escalations table

Revision ID: 06d4c355ee84
Revises: '0003_case_payment_link'
Create Date: 2026-08-25 08:53:50.627841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06d4c355ee84'
down_revision: Union[str, None] = '0003_case_payment_link'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'escalations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('priority', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=True),
        sa.Column('recommended_action', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_escalations_case_id'), 'escalations', ['case_id'], unique=False)
    op.create_index(op.f('ix_escalations_id'), 'escalations', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_escalations_id'), table_name='escalations')
    op.drop_index(op.f('ix_escalations_case_id'), table_name='escalations')
    op.drop_table('escalations')
