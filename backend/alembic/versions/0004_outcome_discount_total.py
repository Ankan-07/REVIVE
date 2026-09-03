"""Add discount_total to recovery_outcomes

Persists the per-outcome discount that update_ledger already computes (sum of the case's
intervention discounts) so the analytics ledger can sum a stored column instead of back-deriving
discounts from gross − cost − net.

Revision ID: 0004_outcome_discount_total
Revises: 06d4c355ee84
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_outcome_discount_total'
down_revision: Union[str, None] = '06d4c355ee84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recovery_outcomes',
        sa.Column('discount_total', sa.Float(), nullable=True, server_default='0.0'),
    )


def downgrade() -> None:
    # batch_alter_table so DROP COLUMN works on SQLite as well as server databases.
    with op.batch_alter_table('recovery_outcomes') as batch_op:
        batch_op.drop_column('discount_total')
