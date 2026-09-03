"""Simulated recovery tools (PRD §11, §38, §39). See :mod:`app.tools.payment_tools`."""

from app.tools.payment_tools import TOOL_FOR_ACTION as PAYMENT_TOOLS
from app.tools.checkout_tools import TOOL_FOR_ACTION as CHECKOUT_TOOLS
from app.tools.invoice_tools import TOOL_FOR_ACTION as INVOICE_TOOLS

# Combine all tools into a single dispatch table
TOOL_FOR_ACTION = {**PAYMENT_TOOLS, **CHECKOUT_TOOLS, **INVOICE_TOOLS}
