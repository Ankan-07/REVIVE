"""Diagnose-node prompts (PRD §14, §32).

The model is asked to name a *root cause* only — never an action, never a number it made up. It
returns JSON matching :class:`app.agent.contracts.Diagnosis`. The system rules encode the guardrails
from §32: stay grounded in the provided signals, express calibrated confidence, cite evidence.
"""
from __future__ import annotations

import json
from typing import Any, Dict

DIAGNOSE_SYSTEM = (
    "You are the diagnosis stage of an autonomous revenue-recovery agent for an Indian SaaS/D2C "
    "business. Given structured signals about a revenue leak (FAILED payment, ABANDONED checkout, "
    "or OVERDUE invoice), identify the single most likely ROOT CAUSE of the leak.\n"
    "Rules:\n"
    "1. Diagnose only — do NOT propose or rank recovery actions (a later stage does that).\n"
    "2. Ground every claim in the signals provided. Do not invent facts or numbers.\n"
    "3. Give a calibrated confidence in [0,1]; be less confident when signals are weak or conflicting.\n"
    "4. Common root causes for payments: card_declined, upi_timeout, netbanking_drop, gateway_degradation, insufficient_funds, expired_card, timeout.\n"
    "5. Common root causes for checkouts: price_shock, intent_loss, technical_friction.\n"
    "6. Common root causes for invoices: forgot_to_pay, awaiting_approval, temporary_cashflow_issue.\n"
    "7. If the leak is an invoice and the communications array contains a customer reply promising to pay by a specific date, extract that ISO8601 date into `promise_to_pay_date`.\n"
    "Respond with ONLY a JSON object of the form "
    '{"type": <snake_case_string>, "confidence": <float 0..1>, "evidence": [<string>, ...], "promise_to_pay_date": <optional_iso_date>}.'
)


def build_diagnose_user(context: Dict[str, Any]) -> str:
    """Render the case context into the user turn for diagnosis."""
    return (
        f"Diagnose the root cause of this {context.get('case_type', 'revenue')} leak from the following signals:\n"
        f"{json.dumps(context, indent=2)}\n\n"
        "Return only the JSON diagnosis object."
    )
