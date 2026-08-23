from typing import Type
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db import Base


# Map of prefix string to model class name or lazy import to prevent circular dependencies
PREFIX_MAP = {
    "CUS": ("app.models.customer", "Customer"),
    "PAY": ("app.models.payment", "Payment"),
    "ORD": ("app.models.order", "Order"),
    "CHK": ("app.models.checkout", "Checkout"),
    "INV": ("app.models.invoice", "Invoice"),
    "RR": ("app.models.case", "RevenueRiskCase"),
    "INT": ("app.models.intervention", "Intervention"),
    "DEC": ("app.models.decision", "AgentDecision"),
    "POL": ("app.models.policy", "Policy"),
    "COM": ("app.models.communication", "Communication"),
    "P2P": ("app.models.promise", "PromiseToPay"),
    "ESC": ("app.models.escalation", "Escalation"),
    "AUD": ("app.models.audit", "AuditEvent"),
    "GWM": ("app.models.metric", "GatewayMetric"),
    "OUT": ("app.models.outcome", "RecoveryOutcome"),
    "SIM": ("app.models.simulation", "SimulationRun"),
}


def get_model_class(prefix: str) -> Type[Base]:
    if prefix not in PREFIX_MAP:
        raise ValueError(f"Unknown prefix: {prefix}")
    module_path, class_name = PREFIX_MAP[prefix]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def generate_id(prefix: str, session: Session) -> str:
    """
    Generates sequential string primary key formatted as PREFIX-00001.
    """
    model_cls = get_model_class(prefix)
    count = session.query(func.count(model_cls.id)).scalar() or 0
    next_num = count + 1
    return f"{prefix}-{next_num:05d}"
