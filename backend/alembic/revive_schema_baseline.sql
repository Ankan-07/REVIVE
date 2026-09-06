-- Revenue Rescue Engine (REVIVE) Database Baseline Schema
-- Alembic Head: 0004_outcome_discount_total
-- Snapshot source: revive.db (SQLite)

-- INDEX: ix_agent_decisions_case_id
CREATE INDEX ix_agent_decisions_case_id ON agent_decisions (case_id);

-- INDEX: ix_agent_decisions_id
CREATE INDEX ix_agent_decisions_id ON agent_decisions (id);

-- INDEX: ix_audit_events_case_id
CREATE INDEX ix_audit_events_case_id ON audit_events (case_id);

-- INDEX: ix_audit_events_event_type
CREATE INDEX ix_audit_events_event_type ON audit_events (event_type);

-- INDEX: ix_audit_events_id
CREATE INDEX ix_audit_events_id ON audit_events (id);

-- INDEX: ix_checkouts_customer_id
CREATE INDEX ix_checkouts_customer_id ON checkouts (customer_id);

-- INDEX: ix_checkouts_id
CREATE INDEX ix_checkouts_id ON checkouts (id);

-- INDEX: ix_communications_case_id
CREATE INDEX ix_communications_case_id ON communications (case_id);

-- INDEX: ix_communications_customer_id
CREATE INDEX ix_communications_customer_id ON communications (customer_id);

-- INDEX: ix_communications_id
CREATE INDEX ix_communications_id ON communications (id);

-- INDEX: ix_customers_email
CREATE INDEX ix_customers_email ON customers (email);

-- INDEX: ix_customers_id
CREATE INDEX ix_customers_id ON customers (id);

-- INDEX: ix_escalations_case_id
CREATE INDEX ix_escalations_case_id ON escalations (case_id);

-- INDEX: ix_escalations_id
CREATE INDEX ix_escalations_id ON escalations (id);

-- INDEX: ix_gateway_metrics_gateway_name
CREATE INDEX ix_gateway_metrics_gateway_name ON gateway_metrics (gateway_name);

-- INDEX: ix_gateway_metrics_id
CREATE INDEX ix_gateway_metrics_id ON gateway_metrics (id);

-- INDEX: ix_interventions_case_id
CREATE INDEX ix_interventions_case_id ON interventions (case_id);

-- INDEX: ix_interventions_id
CREATE INDEX ix_interventions_id ON interventions (id);

-- INDEX: ix_invoices_customer_id
CREATE INDEX ix_invoices_customer_id ON invoices (customer_id);

-- INDEX: ix_invoices_id
CREATE INDEX ix_invoices_id ON invoices (id);

-- INDEX: ix_orders_customer_id
CREATE INDEX ix_orders_customer_id ON orders (customer_id);

-- INDEX: ix_orders_id
CREATE INDEX ix_orders_id ON orders (id);

-- INDEX: ix_payments_customer_id
CREATE INDEX ix_payments_customer_id ON payments (customer_id);

-- INDEX: ix_payments_id
CREATE INDEX ix_payments_id ON payments (id);

-- INDEX: ix_payments_order_id
CREATE INDEX ix_payments_order_id ON payments (order_id);

-- INDEX: ix_policies_id
CREATE INDEX ix_policies_id ON policies (id);

-- INDEX: ix_promises_to_pay_case_id
CREATE INDEX ix_promises_to_pay_case_id ON promises_to_pay (case_id);

-- INDEX: ix_promises_to_pay_customer_id
CREATE INDEX ix_promises_to_pay_customer_id ON promises_to_pay (customer_id);

-- INDEX: ix_promises_to_pay_id
CREATE INDEX ix_promises_to_pay_id ON promises_to_pay (id);

-- INDEX: ix_recovery_outcomes_case_id
CREATE INDEX ix_recovery_outcomes_case_id ON recovery_outcomes (case_id);

-- INDEX: ix_recovery_outcomes_id
CREATE INDEX ix_recovery_outcomes_id ON recovery_outcomes (id);

-- INDEX: ix_revenue_risk_cases_case_type
CREATE INDEX ix_revenue_risk_cases_case_type ON revenue_risk_cases (case_type);

-- INDEX: ix_revenue_risk_cases_customer_id
CREATE INDEX ix_revenue_risk_cases_customer_id ON revenue_risk_cases (customer_id);

-- INDEX: ix_revenue_risk_cases_id
CREATE INDEX ix_revenue_risk_cases_id ON revenue_risk_cases (id);

-- INDEX: ix_revenue_risk_cases_payment_id
CREATE INDEX ix_revenue_risk_cases_payment_id ON revenue_risk_cases (payment_id);

-- INDEX: ix_revenue_risk_cases_status
CREATE INDEX ix_revenue_risk_cases_status ON revenue_risk_cases (status);

-- INDEX: ix_simulation_runs_id
CREATE INDEX ix_simulation_runs_id ON simulation_runs (id);

-- TABLE: agent_decisions
CREATE TABLE agent_decisions (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	node_name VARCHAR NOT NULL, 
	input_state_json JSON, 
	output_decision_json JSON, 
	reasoning TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id)
);

-- TABLE: alembic_version
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- TABLE: audit_events
CREATE TABLE audit_events (
	id VARCHAR NOT NULL, 
	case_id VARCHAR, 
	event_type VARCHAR NOT NULL, 
	actor VARCHAR NOT NULL, 
	payload_json JSON, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id)
);

-- TABLE: checkouts
CREATE TABLE checkouts (
	id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	cart_value FLOAT NOT NULL, 
	items_json JSON, 
	abandoned_at DATETIME, 
	status VARCHAR NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: communications
CREATE TABLE communications (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	recipient VARCHAR NOT NULL, 
	template_id VARCHAR, 
	content TEXT NOT NULL, 
	status VARCHAR NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: customers
CREATE TABLE customers (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	email VARCHAR NOT NULL, 
	phone VARCHAR, 
	segment VARCHAR, 
	ltv_amount FLOAT, 
	risk_score FLOAT, 
	created_at DATETIME, 
	updated_at DATETIME, intent_score FLOAT, 
	PRIMARY KEY (id)
);

-- TABLE: escalations
CREATE TABLE escalations (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	reason VARCHAR NOT NULL, 
	priority VARCHAR, 
	owner_id VARCHAR, 
	recommended_action VARCHAR, 
	notes TEXT, 
	status VARCHAR NOT NULL, 
	created_at DATETIME, 
	resolved_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id)
);

-- TABLE: gateway_metrics
CREATE TABLE gateway_metrics (
	id VARCHAR NOT NULL, 
	gateway_name VARCHAR NOT NULL, 
	success_rate FLOAT NOT NULL, 
	latency_ms FLOAT NOT NULL, 
	health_status VARCHAR NOT NULL, 
	recorded_at DATETIME, baseline_success_rate FLOAT, 
	PRIMARY KEY (id)
);

-- TABLE: interventions
CREATE TABLE interventions (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	intervention_type VARCHAR NOT NULL, 
	cost FLOAT, 
	discount_amount FLOAT, 
	status VARCHAR NOT NULL, 
	payload_json JSON, 
	executed_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id)
);

-- TABLE: invoices
CREATE TABLE invoices (
	id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	due_date DATETIME NOT NULL, 
	status VARCHAR NOT NULL, 
	pdf_url VARCHAR, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: orders
CREATE TABLE orders (
	id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR, 
	status VARCHAR NOT NULL, 
	items_json JSON, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: payments
CREATE TABLE "payments" (
	id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR, 
	gateway VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	error_code VARCHAR, 
	error_message VARCHAR, 
	attempt_count INTEGER, 
	created_at DATETIME, 
	order_id VARCHAR, 
	method_health FLOAT, 
	recovery_roll FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_payments_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: policies
CREATE TABLE policies (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description VARCHAR, 
	rules_json JSON NOT NULL, 
	is_active BOOLEAN, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- TABLE: promises_to_pay
CREATE TABLE promises_to_pay (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	promised_amount FLOAT NOT NULL, 
	promised_date DATETIME NOT NULL, 
	status VARCHAR NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: recovery_outcomes
CREATE TABLE recovery_outcomes (
	id VARCHAR NOT NULL, 
	case_id VARCHAR NOT NULL, 
	outcome_type VARCHAR NOT NULL, 
	gross_recovered FLOAT, 
	net_recovered FLOAT, 
	cost_total FLOAT, 
	verified_at DATETIME, 
	created_at DATETIME, discount_total FLOAT DEFAULT '0.0', 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES revenue_risk_cases (id)
);

-- TABLE: revenue_risk_cases
CREATE TABLE "revenue_risk_cases" (
	id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	case_type VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	amount_at_risk FLOAT NOT NULL, 
	net_recovered_amount FLOAT, 
	priority VARCHAR, 
	risk_score FLOAT, 
	diagnosis_json JSON, 
	current_action VARCHAR, 
	attempt_count INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	payment_id VARCHAR, 
	recovery_probability FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_revenue_risk_cases_payment_id_payments FOREIGN KEY(payment_id) REFERENCES payments (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);

-- TABLE: simulation_runs
CREATE TABLE simulation_runs (
	id VARCHAR NOT NULL, 
	seed INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	config_json JSON, 
	metrics_json JSON, 
	status VARCHAR NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);
