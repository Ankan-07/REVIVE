"""Add gateway_fee_paise to recovery_outcomes

Phase B3: Books actual payment gateway fees directly from the capture payload
into recovery_outcomes, ending flat fee assumptions and calculating deterministic
net recovery as gross - cost - discount - gateway_fee.

Revision ID: 0010_gateway_fee_outcome
Revises: 0009_jobs_table
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010_gateway_fee_outcome'
down_revision: Union[str, None] = '0009_jobs_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recovery_outcomes',
        sa.Column('gateway_fee_paise', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    with op.batch_alter_table('recovery_outcomes') as batch_op:
        batch_op.drop_column('gateway_fee_paise')
