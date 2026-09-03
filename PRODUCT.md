# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Revenue Ops / Finance teams monitoring the AI's autonomous recovery actions and metrics.

## Product Purpose

An autonomous AI agent revenue recovery system (REVIVE) designed to identify revenue at risk (such as failed payments, abandoned checkouts, and overdue invoices), diagnose the cause, decide optimal economic recovery interventions, execute actions, and verify financial outcomes. It focuses on maximizing expected net recovered revenue.

## Positioning

The product goes beyond merely detecting or predicting lost revenue—it takes autonomous action within strict boundaries. It behaves as a controlled autonomous operator rather than a chatbot, and is evaluated against a baseline strategy to prove the AI agent performs better than naïve recovery automation.

## Operating Context

Internal dashboard for operators to monitor revenue risk cases, view agent interventions, track intervention costs, and review human escalations.

## Capabilities and Constraints

- Strict auditability and idempotent financial actions.
- The LLM proposes; deterministic code disposes (policy engine enforces boundaries).
- Service layer is the sole DB boundary.
- Existing FastAPI/React stack must be preserved.
- Baseline strategy comparison must be preserved.

## Evidence on Hand

- PRD (prd.md) with detailed revenue risk cases and product thesis.
- Architecture principles documented in README.md.

## Product Principles

- Maximize expected net recovered revenue, not just action volume.
- Complete financial auditability and idempotency for all operations.
- Deterministic guardrails always override AI proposals.
