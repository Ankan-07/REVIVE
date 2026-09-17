"""Add comms tracking columns to communications table

Phase C: MockCommsProvider and communication tracking.
Adds provider, provider_message_id, delivered_at, and reply_body.

Revision ID: 0013_comms_tracking
Revises: 0012_escalation_sla_due_at
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013_comms_tracking'
down_revision: Union[str, None] = '0012_escalation_sla_due_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('communications', sa.Column('provider', sa.String(), nullable=True, server_default='mock_comms'))
    op.add_column('communications', sa.Column('provider_message_id', sa.String(), nullable=True))
    op.add_column('communications', sa.Column('delivered_at', sa.DateTime(), nullable=True))
    op.add_column('communications', sa.Column('reply_body', sa.Text(), nullable=True))
    op.create_index(op.f('ix_communications_provider_message_id'), 'communications', ['provider_message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_communications_provider_message_id'), table_name='communications')
    op.drop_column('communications', 'reply_body')
    op.drop_column('communications', 'delivered_at')
    op.drop_column('communications', 'provider_message_id')
    op.drop_column('communications', 'provider')
