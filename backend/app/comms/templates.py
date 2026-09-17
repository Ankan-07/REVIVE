"""Templates registry and renderer for communications (Phase C)."""
from __future__ import annotations

from typing import Any, Dict

TEMPLATES = {
    "payment_reminder": (
        "Hi {customer_name}, your recent payment of ₹{amount:.2f} was unsuccessful. "
        "Please update your payment method or complete it here: {payment_link}."
    ),
    "checkout_reminder": (
        "Hi {customer_name}, you left items in your cart totaling ₹{amount:.2f}. "
        "Complete your purchase here: {payment_link}."
    ),
    "invoice_nudge": (
        "Hi {customer_name}, invoice {invoice_id} for ₹{amount:.2f} is overdue. "
        "Please settle your invoice at: {payment_link}."
    ),
    "discount_offer": (
        "Hi {customer_name}, save {discount_percent}% on your order! "
        "Complete your payment now using code {discount_code}: {payment_link}."
    ),
}


def render_template(template_id: str, context: Dict[str, Any]) -> str:
    """Render template by template_id with fallback values."""
    tmpl = TEMPLATES.get(template_id)
    if not tmpl:
        # Fallback generic format
        return f"Payment notification: {context.get('payment_link', '')}"

    clean_context = {
        "customer_name": context.get("customer_name") or "Valued Customer",
        "amount": float(context.get("amount", 0.0)),
        "payment_link": context.get("payment_link") or "https://rzp.io/l/pay",
        "invoice_id": context.get("invoice_id") or "INV-1001",
        "discount_percent": context.get("discount_percent") or 10,
        "discount_code": context.get("discount_code") or "SAVE10",
    }
    return tmpl.format(**clean_context)
