"""Add origin column to customers, payments, and revenue_risk_cases

A1.8: Adds origin column ('live' | 'lab') with default 'lab' and index
across root entities for dual-track live vs lab quarantine.

Revision ID: 0007_origin_timezone
Revises: 0006_provider_objects
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007_origin_timezone'
down_revision: Union[str, None] = '0006_provider_objects'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. customers.origin
    op.add_column('customers', sa.Column('origin', sa.String(length=16), server_default='lab', nullable=False))
    op.create_index('ix_customers_origin', 'customers', ['origin'], unique=False)

    # 2. payments.origin
    op.add_column('payments', sa.Column('origin', sa.String(length=16), server_default='lab', nullable=False))
    op.create_index('ix_payments_origin', 'payments', ['origin'], unique=False)

    # 3. revenue_risk_cases.origin
    op.add_column('revenue_risk_cases', sa.Column('origin', sa.String(length=16), server_default='lab', nullable=False))
    op.create_index('ix_revenue_risk_cases_origin', 'revenue_risk_cases', ['origin'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_revenue_risk_cases_origin', table_name='revenue_risk_cases')
    op.drop_column('revenue_risk_cases', 'origin')

    op.drop_index('ix_payments_origin', table_name='payments')
    op.drop_column('payments', 'origin')

    op.drop_index('ix_customers_origin', table_name='customers')
    op.drop_column('customers', 'origin')
