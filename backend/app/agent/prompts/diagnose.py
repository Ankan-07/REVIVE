"""Diagnose-node prompts (PRD §14, §32).

The model is asked to name a *root cause* only — never an action, never a number it made up. It
returns JSON matching :class:`app.agent.contracts.Diagnosis`. The system rules encode the guardrails
from §32: stay grounded in the provided signals, express calibrated confidence, cite evidence.
"""
from __future__ import annotations

import json
from typing import Any, Dict

DIAGNOSE_SYSTEM = (
    "You are the diagnosis stage of an autonomous payment-recovery agent for an Indian SaaS/D2C "
    "business. Given structured signals about a single FAILED payment, identify the single most "
    "likely ROOT CAUSE of the failure.\n"
    "Rules:\n"
    "1. Diagnose only — do NOT propose or rank recovery actions (a later stage does that).\n"
    "2. Ground every claim in the signals provided. Do not invent facts or numbers.\n"
    "3. Give a calibrated confidence in [0,1]; be less confident when signals are weak or conflicting.\n"
    "4. Common root causes: gateway_degradation, insufficient_funds, expired_or_invalid_method, "
    "network_timeout, risk_or_fraud_block, unknown.\n"
    "Respond with ONLY a JSON object of the form "
    '{"type": <snake_case_string>, "confidence": <float 0..1>, "evidence": [<string>, ...]}.'
)


def build_diagnose_user(context: Dict[str, Any]) -> str:
    """Render the case context into the user turn for diagnosis."""
    facts = {
        "amount_at_risk": context.get("amount_at_risk"),
        "currency": context.get("currency"),
        "error_code": context.get("error_code"),
        "current_gateway": context.get("gateway"),
        "current_gateway_success_rate": context.get("gateway_success_rate"),
        "current_gateway_baseline_rate": context.get("gateway_baseline_rate"),
        "gateway_degraded": context.get("gateway_degraded"),
        "method_health": context.get("method_health"),
        "customer_intent": context.get("customer_intent"),
        "customer_segment": context.get("customer_segment"),
        "alternative_gateways": context.get("alternative_gateways"),
    }
    return (
        "Diagnose the root cause of this failed payment from the following signals:\n"
        f"{json.dumps(facts, indent=2)}\n\n"
        "Return only the JSON diagnosis object."
    )
