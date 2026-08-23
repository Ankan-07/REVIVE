# Revenue Rescue Engine

## AI Agent Product Requirements Document and Build Context

**Project codename:** REVIVE
**Product:** Revenue Rescue Engine
**Document type:** Product Requirements Document + Technical Build Context
**Primary audience:** AI coding agents such as Claude Code, implementation engineers, hackathon judges, and project collaborators
**Version:** 1.0
**Status:** Build-ready specification
**Primary objective:** Detect revenue at risk, diagnose why it is at risk, select the most economically sensible recovery intervention, execute the intervention within strict bounds, and verify the resulting financial outcome.

---

# 1. Executive Summary

Revenue Rescue Engine is an AI-powered revenue recovery system designed to identify revenue that is slipping out of a business and autonomously attempt to recover it.

The system treats each potential revenue leak as a **Revenue Risk Case** and manages that case through a controlled agent workflow:

```text
Detect
  ↓
Understand
  ↓
Estimate
  ↓
Decide
  ↓
Policy Check
  ↓
Act
  ↓
Observe
  ↓
Recover / Continue / Escalate
  ↓
Record Outcome
```

The product should support multiple revenue leak categories, but the initial MVP will focus on:

1. Failed payments
2. Abandoned checkout
3. Overdue B2B invoices

The core differentiator is that the product does **not** stop at detecting or predicting lost revenue.

It must demonstrate measurable recovery.

Example:

```text
Revenue at risk:        ₹22,40,000
Agent interventions:    1,102
Revenue recovered:      ₹7,80,000
Intervention cost:      ₹48,000
Net revenue recovered:  ₹7,32,000
Human escalations:      93
```

The product should be evaluated against a simple baseline strategy to determine whether the AI agent actually performs better than naïve recovery automation.

The system should prioritize **expected net recovered revenue**, not merely recovery rate.

---

# 2. Product Vision

## Vision

Build an AI revenue operations agent that can take responsibility for a revenue-loss problem from detection through resolution while maintaining strict financial, communication, and operational boundaries.

The system should behave less like a chatbot and more like a controlled autonomous operator.

The agent should answer:

> What revenue is currently at risk?

> Why is it at risk?

> What intervention is most likely to recover it?

> What will that intervention cost?

> Is the action permitted?

> What happened after the action?

> Did the business actually recover money?

---

# 3. Problem Statement

Businesses routinely lose revenue through fragmented failure points:

```text
Payment failure
Checkout abandonment
Subscription renewal failure
Invoice delinquency
Broken payment promises
Gateway degradation
Customer communication failure
```

The underlying business systems usually contain enough information to identify these events, but the recovery process is often fragmented across:

```text
Payment provider
Checkout platform
CRM
Subscription system
Invoice system
Email / WhatsApp
Support software
Accounting system
```

Humans or simple automation typically perform one action at a time.

For example:

```text
Payment failed
→ retry payment

Invoice overdue
→ send reminder

Cart abandoned
→ send email
```

This is insufficient because the correct intervention depends on context.

A payment failure caused by gateway degradation should potentially receive a different response from a card-expired failure.

A ₹999 abandoned cart should not receive the same treatment as a ₹1,00,000 B2B purchase.

A loyal high-LTV customer may warrant a different recovery path from a new low-intent customer.

The system therefore needs contextual decision-making.

---

# 4. Product Thesis

The product is based on five principles.

## Principle 1: Detection is not recovery

Finding ₹10 lakh of potential lost revenue is useful.

Recovering ₹4 lakh of it is much more useful.

The system must measure actual financial outcomes.

---

## Principle 2: Every intervention has an economic cost

Messages, discounts, gateway changes, human intervention, and repeated retries have costs.

The agent should optimize for:

```text
Expected Net Recovery
=
Expected Recovered Revenue
-
Intervention Cost
-
Discount / Incentive Cost
```

---

## Principle 3: Autonomy must be bounded

The AI must never have unrestricted financial authority.

The agent proposes actions through tools.

A separate policy layer validates those actions.

---

## Principle 4: Every decision must be explainable

Every action must have:

```text
Reason
Evidence
Expected outcome
Policy justification
Actual outcome
```

---

## Principle 5: The workflow ends in an outcome

Every case should eventually become one of:

```text
RECOVERED
EXPIRED
ESCALATED
CLOSED_NO_RECOVERY
```

The system must not create endless autonomous loops.

---

# 5. Goals

## Primary goals

The MVP must:

1. Detect revenue-risk events from structured data and event streams.
2. Create revenue-risk cases.
3. Aggregate relevant customer and transaction context.
4. Diagnose the likely cause of the revenue risk.
5. Estimate recovery probability.
6. Identify valid intervention options.
7. Estimate expected net recovery.
8. Select the best permitted intervention.
9. Execute the intervention through controlled tools.
10. Observe the outcome.
11. Continue or stop based on explicit rules.
12. Escalate cases that require human intervention.
13. Maintain a complete audit trail.
14. Quantify actual recovered money.
15. Compare agent performance against a baseline.

---

# 6. Non-Goals

The MVP should NOT attempt to become a production payment processor.

Do not build:

* A real payment gateway
* A full accounting platform
* A full CRM
* A generalized autonomous business operator
* Unlimited autonomous financial transactions
* Production-scale financial infrastructure
* An unrestricted LLM agent with direct database write access

The project is a revenue-recovery orchestration layer.

---

# 7. Target Users

## Primary user: Revenue / Finance Manager

Needs to know:

```text
Where are we losing money?
How much is recoverable?
What is the agent doing?
How much has been recovered?
Which customers require human intervention?
```

---

## Secondary user: Operations Manager

Needs:

```text
Recovery queue
Automation status
Escalations
Agent decisions
Workflow failures
```

---

## Secondary user: Business Owner

Needs:

```text
Revenue at risk
Revenue recovered
Net recovery
Recovery rate
ROI
```

---

## Secondary user: Finance Operator

Needs:

```text
Overdue invoices
Promise-to-pay commitments
Escalations
Payment status
Audit history
```

---

# 8. Core Product Concepts

## 8.1 Revenue Risk Event

A raw event indicating potential revenue loss.

Examples:

```text
PAYMENT_FAILED
CHECKOUT_ABANDONED
SUBSCRIPTION_RENEWAL_FAILED
INVOICE_OVERDUE
PAYMENT_PROMISE_BROKEN
GATEWAY_DEGRADED
```

Example:

```json
{
  "event_id": "EVT-10291",
  "type": "PAYMENT_FAILED",
  "customer_id": "CUS-8821",
  "amount": 14999,
  "currency": "INR",
  "timestamp": "2026-08-23T10:41:03Z",
  "failure_reason": "gateway_timeout",
  "gateway": "gateway_a"
}
```

---

## 8.2 Revenue Risk Case

A structured object created from a revenue-risk event.

Example:

```json
{
  "case_id": "RR-10291",
  "type": "failed_payment",
  "customer_id": "CUS-8821",
  "amount_at_risk": 14999,
  "currency": "INR",
  "risk_score": 0.86,
  "recovery_probability": 0.79,
  "priority": "HIGH",
  "status": "ACTION_REQUIRED"
}
```

A case is the central entity in the application.

---

## 8.3 Intervention

An action intended to recover revenue.

Examples:

```text
RETRY_PAYMENT
SWITCH_GATEWAY
SEND_PAYMENT_LINK
SEND_WHATSAPP
SEND_EMAIL
SEND_SMS
OFFER_DISCOUNT
REQUEST_PAYMENT_DATE
RECORD_PROMISE_TO_PAY
ESCALATE_TO_HUMAN
```

---

## 8.4 Recovery Outcome

The actual result of the intervention.

Examples:

```text
PAYMENT_SUCCESS
CUSTOMER_RESPONDED
PAYMENT_LINK_OPENED
PURCHASE_COMPLETED
PROMISE_CREATED
PROMISE_BROKEN
NO_RESPONSE
ACTION_FAILED
```

---

## 8.5 Audit Event

Every important state transition or action must produce an audit event.

Example:

```json
{
  "timestamp": "2026-08-23T10:41:06Z",
  "case_id": "RR-10291",
  "event": "INTERVENTION_SELECTED",
  "action": "SWITCH_GATEWAY",
  "reason": "gateway_a_degradation",
  "policy_result": "APPROVED"
}
```

---

# 9. Supported Revenue Leak Types

## MVP 1: Failed Payment

Input:

```text
Customer
Amount
Payment method
Gateway
Failure reason
Timestamp
Previous payment history
```

Agent responsibilities:

```text
Determine likely cause
Determine customer intent
Check gateway health
Estimate retry success
Select recovery action
Execute action
Verify payment
```

---

## MVP 2: Abandoned Checkout

Input:

```text
Customer
Cart value
Cart items
Checkout stage
Last activity
Previous orders
Previous abandoned carts
Customer segment
```

Agent responsibilities:

```text
Determine purchase intent
Select contact channel
Determine message timing
Determine whether incentive is justified
Send recovery action
Monitor interaction
Verify purchase
```

---

## MVP 3: Overdue Invoice

Input:

```text
Customer
Invoice amount
Invoice age
Contract/payment terms
Previous payment behavior
Communication history
Account value
```

Agent responsibilities:

```text
Classify urgency
Determine reminder strategy
Send communication
Detect customer response
Extract promise-to-pay
Track promised date
Verify payment
Escalate when necessary
```

---

# 10. Agent Architecture

The system should use an explicit stateful workflow rather than an unconstrained autonomous agent.

Recommended architecture:

```text
                   ┌─────────────────────┐
                   │ External Events      │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Event Ingestion      │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Risk Detector        │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Context Builder      │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Diagnosis Agent      │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Recovery Planner     │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Policy Engine        │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Tool Executor        │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Outcome Monitor      │
                   └──────────┬──────────┘
                              ↓
              ┌───────────────┼────────────────┐
              ↓               ↓                ↓
         RECOVERED         CONTINUE         ESCALATE
              ↓               ↓                ↓
              └───────────────┼────────────────┘
                              ↓
                   ┌─────────────────────┐
                   │ Revenue Ledger       │
                   └─────────────────────┘
```

---

# 11. Agent State Machine

Use deterministic states.

Recommended states:

```text
DETECTED
CONTEXT_LOADING
DIAGNOSING
PLANNING
POLICY_CHECK
ACTION_PENDING
ACTION_EXECUTING
WAITING_FOR_OUTCOME
RECOVERED
CONTINUE_RECOVERY
ESCALATED
EXPIRED
CLOSED_NO_RECOVERY
```

A case should never jump directly from:

```text
DETECTED → arbitrary financial action
```

Every financial action must pass through:

```text
PLANNING → POLICY_CHECK → ACTION_EXECUTING
```

---

# 12. Agent Responsibilities

The AI agent should perform reasoning, but critical boundaries should remain deterministic.

## LLM responsibilities

The LLM can:

* Interpret transaction context
* Classify failure causes
* Summarize customer history
* Estimate likely recovery
* Generate intervention candidates
* Explain the recommendation
* Generate communication content
* Extract promise-to-pay information
* Determine conversational intent

## Deterministic system responsibilities

The application must control:

* Amount limits
* Discount limits
* Retry limits
* Contact limits
* Customer eligibility
* Business-hour rules
* Required approvals
* Idempotency
* Action permissions
* Escalation rules
* Final financial calculations

This division is mandatory.

---

# 13. Context Retrieval

Before the agent makes a decision, the Context Builder should retrieve all relevant data.

Example context:

```text
Customer Profile
Payment History
Order History
Subscription History
Communication History
Support History
Gateway Health
Current Revenue Risk
Business Policies
Previous Recovery Attempts
```

The agent should not receive unnecessary data.

The Context Builder should produce a concise structured context object.

Example:

```json
{
  "customer": {
    "id": "CUS-8821",
    "lifetime_value": 84000,
    "orders": 14,
    "preferred_channel": "whatsapp"
  },
  "payment": {
    "amount": 14999,
    "failure_reason": "timeout",
    "gateway": "gateway_a"
  },
  "gateway": {
    "current_success_rate": 0.72,
    "baseline_success_rate": 0.97
  },
  "recovery_history": {
    "attempts": 1,
    "successful_recoveries": 1
  },
  "policy": {
    "max_retries": 2,
    "max_messages": 3,
    "max_discount_amount": 1000
  }
}
```

---

# 14. Diagnosis Engine

The Diagnosis Agent must answer:

```text
What happened?
Why did it probably happen?
How confident are we?
What evidence supports the diagnosis?
```

Example:

```json
{
  "diagnosis": "gateway_degradation",
  "confidence": 0.91,
  "evidence": [
    "Gateway A success rate dropped from 97% to 72%",
    "Timeout errors increased 4.3x",
    "Gateway B remains within normal operating range"
  ]
}
```

The diagnosis should never be treated as fact when it is probabilistic.

Use explicit confidence.

---

# 15. Recovery Planning

The Recovery Planner generates candidate interventions.

Example:

```json
{
  "candidate_actions": [
    {
      "action": "RETRY_SAME_GATEWAY",
      "expected_recovery_probability": 0.31,
      "estimated_cost": 0
    },
    {
      "action": "SWITCH_GATEWAY",
      "expected_recovery_probability": 0.79,
      "estimated_cost": 20
    },
    {
      "action": "SEND_WHATSAPP",
      "expected_recovery_probability": 0.52,
      "estimated_cost": 10
    }
  ]
}
```

The planner then calculates expected value.

Example:

```text
Action: SWITCH_GATEWAY

Revenue at risk = ₹14,999
Recovery probability = 79%

Expected recovery =
₹14,999 × 0.79
= ₹11,849.21

Estimated intervention cost = ₹20

Expected net recovery =
₹11,829.21
```

The agent chooses the highest expected net recovery among permitted actions.

---

# 16. Policy Engine

The Policy Engine is a hard control layer.

Example policy:

```json
{
  "payment": {
    "max_retries": 2,
    "retry_window_hours": 24
  },
  "messaging": {
    "max_messages_per_case": 3,
    "minimum_hours_between_messages": 6
  },
  "discount": {
    "max_percent": 10,
    "max_absolute_amount": 1000
  },
  "human_approval": {
    "required_above_amount": 100000
  },
  "invoice": {
    "max_automated_reminders": 3
  }
}
```

Example:

```text
Agent proposal:
Offer 20% discount.

Policy:
REJECT

Maximum allowed:
10%
```

The system then asks the planner for an alternative valid action.

---

# 17. Tool Layer

Tools should be typed and restricted.

## Payment tools

```text
check_payment_status()
retry_payment()
switch_payment_gateway()
create_payment_link()
```

## Checkout tools

```text
get_checkout()
get_cart()
get_customer_checkout_history()
mark_recovery_campaign()
```

## Communication tools

```text
send_whatsapp()
send_email()
send_sms()
```

## Invoice tools

```text
get_invoice()
send_invoice_reminder()
record_promise_to_pay()
get_invoice_payment_status()
```

## Customer tools

```text
get_customer_profile()
get_customer_payment_history()
get_customer_order_history()
```

## Escalation tools

```text
create_human_case()
assign_finance_owner()
add_case_note()
```

All tool calls should be logged.

---

# 18. Tool Safety

Tools must enforce:

1. Authentication
2. Authorization
3. Parameter validation
4. Amount validation
5. Idempotency
6. Policy validation
7. Audit logging

The LLM should never construct unrestricted SQL.

The LLM should never directly mutate arbitrary records.

The LLM should never determine financial limits.

---

# 19. Communication Strategy

Communication should be personalized but policy-controlled.

The communication generator receives:

```text
customer name
revenue risk
failure context
preferred language
communication history
brand tone
legal/business constraints
```

Example output intent:

```text
Purpose:
Payment recovery

Channel:
WhatsApp

Tone:
Professional and concise

Do not:
Mention internal payment error codes

Must include:
Secure payment link
```

The system should support simulated communications during MVP development.

---

# 20. Promise-to-Pay Workflow

This is especially important for the overdue invoice workflow.

Customer response:

> "We'll clear this invoice on Friday."

The extraction layer should generate:

```json
{
  "invoice_id": "INV-10291",
  "promised_amount": 450000,
  "promised_date": "2026-08-28",
  "confidence": 0.94
}
```

The system records the promise.

On the promised date:

```text
if invoice_paid:
    mark RECOVERED
else:
    mark PROMISE_BROKEN
    select next action
```

Never rely on a human remembering the promise.

---

# 21. Stopping Rules

Every recovery case must have explicit stopping conditions.

Stop when:

```text
Payment recovered
Purchase completed
Invoice paid
Maximum retries reached
Maximum messages reached
Recovery window expired
Human escalation triggered
Customer opts out
Action becomes invalid
```

The system must never continue indefinitely.

---

# 22. Escalation Rules

Escalation is a first-class outcome.

Examples:

```text
High-value case > ₹1,00,000
Repeated failed recovery attempts
Customer explicitly requests human support
Policy conflict
Low confidence diagnosis
Payment anomaly
Potential fraud signal
Promise-to-pay broken
```

Human escalation should generate:

```json
{
  "case_id": "RR-10291",
  "priority": "HIGH",
  "reason": "PROMISE_BROKEN",
  "recommended_next_action": "FINANCE_FOLLOW_UP",
  "summary": "...",
  "amount_at_risk": 450000
}
```

---

# 23. Revenue Ledger

Every case must contribute to a measurable financial ledger.

Fields:

```text
amount_at_risk
amount_recovered
intervention_cost
discount_given
net_recovered
recovery_timestamp
recovery_source
```

Formula:

```text
net_recovered
=
amount_recovered
-
intervention_cost
-
discount_given
```

At the dashboard level:

```text
Total Revenue at Risk
Total Gross Recovered
Total Intervention Cost
Total Incentive Cost
Total Net Recovered
Recovery Rate
```

---

# 24. Baseline Strategy

The project must include a simple baseline.

Suggested baseline:

```text
Failed payment:
Retry once.

Abandoned checkout:
Send one generic reminder.

Overdue invoice:
Send one generic reminder.
```

No context-aware optimization.

Then compare:

```text
Baseline
vs
Revenue Rescue Engine
```

This comparison is required for demonstrating impact.

---

# 25. Evaluation Metrics

Primary:

```text
Gross Revenue Recovered
Net Revenue Recovered
Recovery Rate
Incremental Revenue vs Baseline
```

Secondary:

```text
Time to Recovery
Interventions per Recovery
Human Escalation Rate
Messages per Recovery
Average Intervention Cost
Discount Cost
False Escalation Rate
Policy Violation Rate
```

Agent quality metrics:

```text
Diagnosis accuracy
Decision consistency
Tool-call correctness
Policy compliance
Stopping-rule compliance
```

---

# 26. Simulation Environment

The MVP should include a deterministic revenue simulation engine.

The simulator generates realistic:

```text
Customers
Orders
Payments
Checkouts
Subscriptions
Invoices
Communication events
Gateway events
Recovery outcomes
```

The simulator should intentionally inject revenue leaks.

Example:

```text
10,000 customers
25,000 orders
18,000 payments
4,000 checkout sessions
2,500 invoices
```

Inject:

```text
5% insufficient-fund payment failures
3% gateway timeout failures
2% expired-card failures
5% checkout abandonment
3% overdue invoices
```

The simulator should produce ground-truth outcomes so recovery strategies can be evaluated objectively.

---

# 27. Reproducibility

The simulation should support a seed.

Example:

```text
simulation_seed = 42
```

The same seed should produce the same dataset.

This allows:

```text
Baseline run
Agent run
```

to be performed over the exact same conditions.

That makes the benchmark credible.

---

# 28. Agent Simulation

Because real money should not be moved during development, payment tools should support a mock/simulation mode.

Example:

```text
POST /simulation/payments/retry
```

The simulator determines whether the payment succeeds based on the configured customer and failure characteristics.

For example:

```text
Customer intent = 0.82
Gateway health = 0.96
Payment method health = 0.91
```

The simulator calculates a probability of recovery.

The exact calculation can remain deterministic under a seeded simulation.

---

# 29. Data Model

Recommended entities:

```text
Customer
Order
Checkout
Payment
Subscription
Invoice
RevenueRiskCase
Intervention
AgentDecision
Policy
Communication
PromiseToPay
Escalation
AuditEvent
GatewayMetric
RecoveryOutcome
SimulationRun
```

---

# 30. Suggested relational schema

## customers

```text
id
name
email
phone
preferred_channel
preferred_language
customer_segment
lifetime_value
created_at
```

## payments

```text
id
customer_id
order_id
amount
currency
gateway
status
failure_reason
attempt_number
created_at
```

## checkouts

```text
id
customer_id
cart_value
stage
status
last_activity_at
completed_at
```

## invoices

```text
id
customer_id
amount
due_date
status
paid_at
```

## revenue_risk_cases

```text
id
customer_id
type
source_id
amount_at_risk
risk_score
recovery_probability
status
priority
created_at
closed_at
```

## interventions

```text
id
case_id
action_type
channel
expected_recovery
estimated_cost
approved
executed_at
result
```

## promises_to_pay

```text
id
case_id
invoice_id
promised_amount
promised_date
status
```

## audit_events

```text
id
case_id
event_type
actor
details
timestamp
```

---

# 31. AI Decision Output Contract

The LLM should always return structured output.

Example:

```json
{
  "diagnosis": {
    "type": "gateway_degradation",
    "confidence": 0.91,
    "evidence": [
      "Gateway A success rate dropped materially",
      "Timeout frequency increased",
      "Alternative gateway is healthy"
    ]
  },
  "recommendation": {
    "action": "SWITCH_GATEWAY",
    "expected_recovery_probability": 0.79,
    "estimated_cost": 20,
    "expected_net_recovery": 11829.21
  },
  "reasoning_summary": "Gateway degradation is the most likely cause..."
}
```

The actual implementation should validate this JSON with a schema before accepting it.

---

# 32. Agent Prompting Strategy

The agent should receive:

```text
SYSTEM POLICY
BUSINESS RULES
CURRENT CASE
CUSTOMER CONTEXT
AVAILABLE TOOLS
AVAILABLE INTERVENTIONS
CURRENT CASE STATE
PREVIOUS ACTIONS
```

The agent should NOT receive unrestricted system access.

The prompt should explicitly instruct:

```text
Never exceed policy limits.
Never invent financial information.
Never claim recovery unless payment verification confirms it.
Do not repeat an action that has already exhausted its retry limit.
Do not expose internal system errors to customers.
Escalate when confidence is insufficient.
Use only approved tools.
```

---

# 33. Dashboard Requirements

## Dashboard Home

Display:

```text
Revenue at Risk
Gross Revenue Recovered
Net Revenue Recovered
Recovery Rate
Cases Processed
Cases Recovered
Escalations
Average Time to Recovery
```

---

## Revenue Risk Breakdown

Charts:

```text
By revenue leak type
By customer segment
By failure reason
By payment gateway
By day
By intervention
```

---

## Recovery Funnel

```text
Revenue at Risk
        ↓
Cases Eligible
        ↓
Interventions Executed
        ↓
Customers Engaged
        ↓
Money Recovered
```

---

## Intervention Performance

Table:

```text
Action
Cases
Success Rate
Average Revenue
Average Cost
Net Recovery
```

Example:

```text
Switch Gateway
312
71%
₹7,240
₹21
₹1,61,000

WhatsApp Recovery
482
42%
₹4,100
₹8
₹8,25,000
```

---

# 34. Case Detail UI

Each case page should contain:

## Summary

```text
Case ID
Customer
Revenue at Risk
Case Type
Priority
Current Status
```

## AI Diagnosis

```text
Root Cause
Confidence
Evidence
```

## Recommended Action

```text
Action
Expected Recovery
Cost
Expected Net Recovery
Policy Status
```

## Timeline

```text
Event
Decision
Action
Outcome
```

## Financial Outcome

```text
Gross Recovered
Costs
Net Recovered
```

## Audit Trail

Raw structured events should be viewable.

---

# 35. Human Escalation Queue

Create a queue with:

```text
Case
Customer
Amount
Reason
Priority
Recommended Action
Age
Owner
```

Priority examples:

```text
CRITICAL
HIGH
MEDIUM
LOW
```

Human operators should be able to:

```text
Approve
Reject
Assign
Close
Add Note
Trigger Action
```

Human overrides must also be audited.

---

# 36. API Requirements

Suggested API structure:

```text
POST /events
GET /cases
GET /cases/{id}
POST /cases/{id}/run-agent
POST /cases/{id}/approve
POST /cases/{id}/escalate

GET /customers/{id}
GET /payments/{id}
GET /invoices/{id}

POST /payments/{id}/retry
POST /payments/{id}/switch-gateway

POST /communications/send

POST /simulation/run
GET /simulation/{id}

GET /analytics/recovery
GET /analytics/interventions
GET /analytics/baseline
```

---

# 37. Asynchronous Workflows

The system should support jobs for actions that wait for external outcomes.

Example:

```text
Payment retry
      ↓
WAITING_FOR_OUTCOME
      ↓
Payment event received
      ↓
Resume case
```

Avoid keeping an HTTP request open while waiting for simulated or real events.

---

# 38. Idempotency

Financial workflows must be idempotent.

A retry request should not accidentally create multiple charges.

Use idempotency keys such as:

```text
case_id + action_type + attempt_number
```

Example:

```text
RR-10291:RETRY_PAYMENT:2
```

If the same action is submitted twice, the tool should return the previous result instead of executing another charge.

---

# 39. Failure Handling

Every tool should return explicit statuses.

Example:

```json
{
  "success": false,
  "error_code": "PAYMENT_GATEWAY_UNAVAILABLE",
  "retryable": true
}
```

The agent should distinguish:

```text
Retryable failure
Non-retryable failure
Policy failure
Authentication failure
External system failure
Customer-side failure
```

---

# 40. Security Requirements

Even for a hackathon implementation:

Do not expose:

```text
Card numbers
CVV
Passwords
Authentication tokens
Private API keys
```

Use only mock payment identifiers.

Store secrets in environment variables.

Never send raw secrets into LLM prompts.

---

# 41. Privacy Requirements

Only provide the agent with the minimum customer context required for the decision.

Avoid unnecessary personal data.

Use synthetic data for the demo.

---

# 42. Observability

The system should log:

```text
Agent execution
Tool calls
Policy decisions
State transitions
Latency
Errors
Recovery results
```

Recommended fields:

```text
request_id
case_id
agent_run_id
tool_call_id
timestamp
state
action
result
latency
```

---

# 43. Logging Example

```text
[10:41:03] CASE_CREATED RR-10291
[10:41:03] STATE DETECTED → CONTEXT_LOADING
[10:41:04] CUSTOMER_CONTEXT_LOADED
[10:41:04] GATEWAY_CONTEXT_LOADED
[10:41:05] DIAGNOSIS gateway_degradation confidence=0.91
[10:41:05] PLAN switch_gateway expected_net=11829.21
[10:41:05] POLICY_CHECK approved
[10:41:06] TOOL switch_gateway
[10:41:08] PAYMENT_SUCCESS amount=14999
[10:41:08] CASE_RECOVERED RR-10291
```

---

# 44. Agent Evaluation

Do not evaluate the project solely by whether the LLM produces plausible text.

Run structured tests.

## Decision tests

Given:

```text
gateway degraded
customer high intent
alternative gateway healthy
```

Expected:

```text
switch gateway
```

---

## Policy tests

Given:

```text
discount requested = 20%
policy maximum = 10%
```

Expected:

```text
action rejected
```

---

## Stopping tests

Given:

```text
max retries = 2
attempts already = 2
```

Expected:

```text
no additional retry
```

---

## Escalation tests

Given:

```text
amount = ₹5,00,000
high-value threshold = ₹1,00,000
```

Expected:

```text
human approval required
```

---

# 45. Baseline Evaluation

Run the same simulation against:

## Baseline

```text
Failed payment:
retry once

Abandoned checkout:
one generic message

Overdue invoice:
one generic reminder
```

## AI Agent

Context-aware decisions with bounded interventions.

Compare:

```text
Total revenue at risk
Gross revenue recovered
Net revenue recovered
Recovery rate
Cost
Human involvement
```

The same simulation seed must be used.

---

# 46. Example Benchmark

Example expected demo result:

```text
                    BASELINE     REVIVE

Revenue at Risk      ₹50.0L       ₹50.0L

Cases Processed       3,800        3,800

Gross Recovered       ₹9.8L        ₹15.6L

Intervention Cost     ₹0.4L        ₹0.7L

Net Recovered         ₹9.4L        ₹14.9L

Recovery Rate         19.6%        31.2%

Human Escalations       420          190
```

The exact numbers are simulation outputs, not predetermined claims.

The implementation must calculate them from the actual simulation.

---

# 47. Critical Product Insight

Do not optimize only for:

```text
Highest Recovery Rate
```

Consider:

```text
Revenue recovered
-
discounts
-
communication costs
-
operational cost
```

A strategy that recovers 50% of customers with huge discounts may be worse than a strategy that recovers 40% without incentives.

The system should therefore optimize:

```text
Expected Net Recovered Revenue
```

---

# 48. Recommended MVP Scope

The MVP should contain:

## Revenue sources

```text
Failed payments
Abandoned checkout
Overdue invoices
```

## Agent capabilities

```text
Risk detection
Context retrieval
Diagnosis
Recovery planning
Policy validation
Tool execution
Outcome monitoring
Escalation
Audit logging
```

## Dashboard

```text
Executive metrics
Revenue-at-risk breakdown
Recovery funnel
Intervention analytics
Case detail
Escalation queue
Audit trail
```

## Simulation

```text
Seeded dataset
Revenue leak injection
Baseline strategy
AI strategy
Comparative analytics
```

---

# 49. Phase 2 Features

After MVP:

```text
Subscription recovery
Payment gateway routing optimization
Promise-to-pay tracker
Hinglish communication
Voice recovery
Customer churn prediction
LLM-based support-ticket context
Adaptive intervention timing
```

These should not block the MVP.

---

# 50. Phase 3 Features

Potential advanced capabilities:

```text
Multi-agent specialization
Cross-channel optimization
Real payment sandbox
Real WhatsApp integration
Real accounting integration
Revenue forecasting
Intervention experimentation
Bandit-based strategy optimization
Long-term customer value modeling
```

---

# 51. Multi-Agent Extension

Do not start with many agents.

Once the single workflow works, the architecture can be decomposed into:

```text
Risk Detection Agent
        ↓
Diagnosis Agent
        ↓
Recovery Strategist
        ↓
Communication Agent
        ↓
Finance Agent
        ↓
Outcome Agent
```

However, each agent must have a bounded responsibility.

A single orchestrator should remain responsible for workflow state.

---

# 52. Suggested Build Order

## Stage 1: Foundation

Build:

```text
PostgreSQL schema
FastAPI backend
React dashboard
Seeded simulation
Basic authentication
```

---

## Stage 2: Revenue Risk Engine

Implement:

```text
Payment failure detection
Checkout abandonment detection
Invoice overdue detection
Case creation
Risk scoring
```

---

## Stage 3: Agent

Implement:

```text
Context retrieval
Diagnosis
Action planning
Structured LLM output
Decision validation
```

---

## Stage 4: Tools

Implement:

```text
Retry payment
Switch gateway
Send message
Create payment link
Record promise
Escalate case
```

Use mocks first.

---

## Stage 5: Policy Engine

Implement:

```text
Retry limits
Discount limits
Messaging limits
Amount thresholds
Time windows
Human approval
```

---

## Stage 6: Outcome Monitoring

Implement:

```text
Payment confirmation
Purchase confirmation
Invoice payment confirmation
Promise verification
Case state transition
```

---

## Stage 7: Analytics

Implement:

```text
Revenue at risk
Gross recovery
Net recovery
Recovery rate
Baseline comparison
Intervention performance
```

---

## Stage 8: Polish

Add:

```text
Case timeline
Agent decision explanation
Audit trail
Simulation controls
Demo dataset
Loading states
Error handling
```

---

# 53. Demo Flow

The final hackathon demonstration should follow this sequence.

## Step 1

Open dashboard.

Show:

```text
₹22.4L Revenue at Risk
```

---

## Step 2

Click:

```text
Run Revenue Rescue
```

---

## Step 3

System processes cases.

Show real-time state transitions.

---

## Step 4

Open a failed payment case.

Show:

```text
Cause:
Gateway degradation

Decision:
Switch gateway

Expected net recovery:
₹11,829
```

---

## Step 5

Execute.

Show:

```text
PAYMENT SUCCESSFUL

₹14,999 RECOVERED
```

---

## Step 6

Open an abandoned checkout.

Agent decides:

```text
No discount.
WhatsApp recovery is more economically efficient.
```

---

## Step 7

Open an overdue invoice.

Customer replies:

```text
"We'll pay on Friday."
```

Agent extracts:

```text
Promise-to-pay:
₹4,50,000
Date:
Friday
```

---

## Step 8

Simulate broken promise.

Agent escalates.

---

## Step 9

Show dashboard:

```text
Before:
₹22.4L at risk

After:
₹15.6L recovered

₹6.8L unresolved

Net recovery:
₹14.9L
```

---

## Step 10

Show:

```text
AI Agent vs Baseline
```

This should be the final proof of impact.

---

# 54. UX Principle

The dashboard should not feel like a generic AI chatbot.

The primary interface should be:

```text
Revenue
Cases
Actions
Outcomes
```

The AI explanation should support the workflow.

Do not make the chat window the primary UI.

The product is an operations system, not a conversational demo.

---

# 55. Error States

Every screen should handle:

```text
Agent unavailable
LLM timeout
Tool failure
Payment simulation failure
Policy rejection
Missing customer data
Malformed agent output
Duplicate action
Unknown case state
```

Never display a successful recovery unless the outcome verifier confirms it.

---

# 56. LLM Reliability Strategy

The system must assume that LLM outputs can be wrong.

Therefore:

```text
LLM proposes
      ↓
Schema validates
      ↓
Policy validates
      ↓
Tool validates
      ↓
Execution occurs
      ↓
Outcome verifies
```

Never:

```text
LLM decides
      ↓
financial action
```

---

# 57. Codebase Architecture

Recommended project structure:

```text
revenue-rescue/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── agents/
│   │   │   ├── orchestrator/
│   │   │   ├── diagnosis/
│   │   │   ├── planner/
│   │   │   └── communication/
│   │   ├── domain/
│   │   ├── models/
│   │   ├── tools/
│   │   ├── policies/
│   │   ├── services/
│   │   ├── simulation/
│   │   ├── analytics/
│   │   ├── audit/
│   │   └── main.py
│   │
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── charts/
│   │   └── types/
│   └── package.json
│
├── simulation/
│   ├── generators/
│   ├── scenarios/
│   └── seeds/
│
├── docs/
│   ├── architecture.md
│   ├── agent.md
│   └── api.md
│
├── docker-compose.yml
└── README.md
```

---

# 58. Engineering Constraints

1. Use typed schemas for agent outputs.
2. Keep financial calculations deterministic.
3. Keep policy decisions deterministic.
4. Use structured tool interfaces.
5. Make tool calls idempotent.
6. Log every action.
7. Make simulation reproducible.
8. Never claim recovery without verified outcome.
9. Keep the LLM outside direct database mutation.
10. Keep the MVP small enough to complete reliably.

---

# 59. Definition of Done

The project is considered MVP-complete when all of the following work end-to-end.

```text
[ ] Synthetic customers can be generated
[ ] Synthetic revenue leaks can be generated
[ ] Revenue-risk events can be detected
[ ] Cases are created automatically
[ ] Customer context is retrieved
[ ] Agent diagnoses cases
[ ] Agent proposes interventions
[ ] Policy engine validates interventions
[ ] Tools execute interventions
[ ] Outcomes are verified
[ ] Cases transition correctly
[ ] Cases stop according to policy
[ ] Cases can be escalated
[ ] Audit trail is generated
[ ] Revenue recovery is measured
[ ] Baseline comparison works
[ ] Dashboard displays financial metrics
[ ] Case details show agent decisions
[ ] Simulation runs are reproducible
[ ] No financial action occurs without policy validation
```

---

# 60. Final Product Definition

Revenue Rescue Engine is not:

```text
A chatbot for payments
A dashboard that predicts churn
A workflow automation tool
A generic RAG application
```

It is:

```text
A bounded autonomous revenue-recovery system.
```

The core product loop is:

```text
                    REVENUE AT RISK
                           │
                           ▼
                       DETECT
                           │
                           ▼
                      DIAGNOSE
                           │
                           ▼
                    ESTIMATE RECOVERY
                           │
                           ▼
                    CHOOSE INTERVENTION
                           │
                           ▼
                     POLICY CHECK
                           │
                           ▼
                        EXECUTE
                           │
                           ▼
                       OBSERVE
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
            RECOVERED   CONTINUE   ESCALATE
                │          │          │
                └──────────┼──────────┘
                           ▼
                     MEASURE MONEY
                           │
                           ▼
                 UPDATE REVENUE LEDGER
```

The central success metric is:

> **How much net revenue did the agent recover that the baseline would not have recovered?**

That should remain the north-star metric throughout implementation.

---

# 61. Build-Agent Instruction

When an AI coding agent such as Claude Code begins implementation, it should treat this document as the source of truth for product behavior.

The coding agent should:

1. Build the smallest complete end-to-end workflow before expanding scope.
2. Prefer deterministic business logic over unnecessary LLM reasoning.
3. Use the LLM only where contextual reasoning or natural-language generation provides value.
4. Never allow the LLM to bypass policies.
5. Keep payment actions simulated during development.
6. Add tests around agent decisions, policies, state transitions, and financial calculations.
7. Maintain clear separation between domain logic, agent orchestration, tools, policies, persistence, and presentation.
8. Avoid implementing phase-2 features until the MVP workflow is functional.
9. Use seeded simulation data for reproducible evaluation.
10. Ensure every claimed recovery is tied to a verified outcome.
11. Keep all agent outputs structured and schema-validated.
12. Preserve auditability for every autonomous action.
13. Optimize for actual recoverable revenue, not superficial agent activity.
14. Prefer a smaller working system with measurable financial impact over a larger system with incomplete workflows.

---

# 62. One-Sentence Product Definition

**REVIVE is an AI revenue recovery agent that finds money at risk, determines the highest-value compliant intervention, executes it through bounded tools, and proves how much revenue was actually recovered.**
