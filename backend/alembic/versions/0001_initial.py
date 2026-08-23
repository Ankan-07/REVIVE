"""0001_initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-23 13:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Customers
    op.create_table(
        'customers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('segment', sa.String(), nullable=True),
        sa.Column('ltv_amount', sa.Float(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customers_email'), 'customers', ['email'], unique=False)
    op.create_index(op.f('ix_customers_id'), 'customers', ['id'], unique=False)

    # 2. Payments
    op.create_table(
        'payments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True),
        sa.Column('gateway', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payments_customer_id'), 'payments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_payments_id'), 'payments', ['id'], unique=False)

    # 3. Orders
    op.create_table(
        'orders',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('items_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_orders_customer_id'), 'orders', ['customer_id'], unique=False)
    op.create_index(op.f('ix_orders_id'), 'orders', ['id'], unique=False)

    # 4. Checkouts
    op.create_table(
        'checkouts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('cart_value', sa.Float(), nullable=False),
        sa.Column('items_json', sa.JSON(), nullable=True),
        sa.Column('abandoned_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checkouts_customer_id'), 'checkouts', ['customer_id'], unique=False)
    op.create_index(op.f('ix_checkouts_id'), 'checkouts', ['id'], unique=False)

    # 5. Invoices
    op.create_table(
        'invoices',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('pdf_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoices_customer_id'), 'invoices', ['customer_id'], unique=False)
    op.create_index(op.f('ix_invoices_id'), 'invoices', ['id'], unique=False)

    # 6. RevenueRiskCases
    op.create_table(
        'revenue_risk_cases',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('case_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('amount_at_risk', sa.Float(), nullable=False),
        sa.Column('net_recovered_amount', sa.Float(), nullable=True),
        sa.Column('priority', sa.String(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('diagnosis_json', sa.JSON(), nullable=True),
        sa.Column('current_action', sa.String(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_revenue_risk_cases_case_type'), 'revenue_risk_cases', ['case_type'], unique=False)
    op.create_index(op.f('ix_revenue_risk_cases_customer_id'), 'revenue_risk_cases', ['customer_id'], unique=False)
    op.create_index(op.f('ix_revenue_risk_cases_id'), 'revenue_risk_cases', ['id'], unique=False)
    op.create_index(op.f('ix_revenue_risk_cases_status'), 'revenue_risk_cases', ['status'], unique=False)

    # 7. Interventions
    op.create_table(
        'interventions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('intervention_type', sa.String(), nullable=False),
        sa.Column('cost', sa.Float(), nullable=True),
        sa.Column('discount_amount', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interventions_case_id'), 'interventions', ['case_id'], unique=False)
    op.create_index(op.f('ix_interventions_id'), 'interventions', ['id'], unique=False)

    # 8. AgentDecisions
    op.create_table(
        'agent_decisions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('node_name', sa.String(), nullable=False),
        sa.Column('input_state_json', sa.JSON(), nullable=True),
        sa.Column('output_decision_json', sa.JSON(), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_decisions_case_id'), 'agent_decisions', ['case_id'], unique=False)
    op.create_index(op.f('ix_agent_decisions_id'), 'agent_decisions', ['id'], unique=False)

    # 9. Policies
    op.create_table(
        'policies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('rules_json', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_policies_id'), 'policies', ['id'], unique=False)

    # 10. Communications
    op.create_table(
        'communications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('channel', sa.String(), nullable=False),
        sa.Column('recipient', sa.String(), nullable=False),
        sa.Column('template_id', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_communications_case_id'), 'communications', ['case_id'], unique=False)
    op.create_index(op.f('ix_communications_customer_id'), 'communications', ['customer_id'], unique=False)
    op.create_index(op.f('ix_communications_id'), 'communications', ['id'], unique=False)

    # 11. PromisesToPay
    op.create_table(
        'promises_to_pay',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('customer_id', sa.String(), nullable=False),
        sa.Column('promised_amount', sa.Float(), nullable=False),
        sa.Column('promised_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_promises_to_pay_case_id'), 'promises_to_pay', ['case_id'], unique=False)
    op.create_index(op.f('ix_promises_to_pay_customer_id'), 'promises_to_pay', ['customer_id'], unique=False)
    op.create_index(op.f('ix_promises_to_pay_id'), 'promises_to_pay', ['id'], unique=False)

    # 12. Escalations
    op.create_table(
        'escalations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('priority', sa.String(), nullable=True),
        sa.Column('owner', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_escalations_case_id'), 'escalations', ['case_id'], unique=False)
    op.create_index(op.f('ix_escalations_id'), 'escalations', ['id'], unique=False)

    # 13. AuditEvents
    op.create_table(
        'audit_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_case_id'), 'audit_events', ['case_id'], unique=False)
    op.create_index(op.f('ix_audit_events_event_type'), 'audit_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_audit_events_id'), 'audit_events', ['id'], unique=False)

    # 14. GatewayMetrics
    op.create_table(
        'gateway_metrics',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('gateway_name', sa.String(), nullable=False),
        sa.Column('success_rate', sa.Float(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('health_status', sa.String(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gateway_metrics_gateway_name'), 'gateway_metrics', ['gateway_name'], unique=False)
    op.create_index(op.f('ix_gateway_metrics_id'), 'gateway_metrics', ['id'], unique=False)

    # 15. RecoveryOutcomes
    op.create_table(
        'recovery_outcomes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('outcome_type', sa.String(), nullable=False),
        sa.Column('gross_recovered', sa.Float(), nullable=True),
        sa.Column('net_recovered', sa.Float(), nullable=True),
        sa.Column('cost_total', sa.Float(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['revenue_risk_cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recovery_outcomes_case_id'), 'recovery_outcomes', ['case_id'], unique=False)
    op.create_index(op.f('ix_recovery_outcomes_id'), 'recovery_outcomes', ['id'], unique=False)

    # 16. SimulationRuns
    op.create_table(
        'simulation_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config_json', sa.JSON(), nullable=True),
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_simulation_runs_id'), 'simulation_runs', ['id'], unique=False)


def downgrade() -> None:
    op.drop_table('simulation_runs')
    op.drop_table('recovery_outcomes')
    op.drop_table('gateway_metrics')
    op.drop_table('audit_events')
    op.drop_table('escalations')
    op.drop_table('promises_to_pay')
    op.drop_table('communications')
    op.drop_table('policies')
    op.drop_table('agent_decisions')
    op.drop_table('interventions')
    op.drop_table('revenue_risk_cases')
    op.drop_table('invoices')
    op.drop_table('checkouts')
    op.drop_table('orders')
    op.drop_table('payments')
    op.drop_table('customers')
