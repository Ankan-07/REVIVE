"""Tests for Phase B2: Razorpay-native action set.

Validates:
- Live vs. Lab menu dispatch (B2.2: SWITCH_GATEWAY dropped on live path)
- Live tool execution (B2.1, B2.3: Orders API and Payment Links API with provider_objects tracking)
- Attempt count alignment with provider_objects (B2.2)
- Native reminders disabled by default (Principle 7) and Communication row recorder on opt-in
- Offline seam isolation for fetch_payment and create_payment_link_for_case (B2.1)
"""
import pytest
from app.agent.menu import allowed_menu
from app.agent.nodes.execute_tool import execute_tool
from app.config import settings
from app.models.case import RevenueRiskCase
from app.models.communication import Communication
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.provider_object import ProviderObject
from app.schemas.enums import CaseStatus, CaseType, InterventionType
from app.services import razorpay_service

KEY_ID = "rzp_test_mock12345678"
KEY_SECRET = "mock_secret_87654321"


@pytest.fixture(autouse=True)
def _setup_razorpay_keys(monkeypatch):
    """Provide valid test-mode keys for B2 action tests."""
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    orig_live = settings.live_recovery_enabled
    orig_reminders = settings.enable_native_reminders
    settings.live_recovery_enabled = True
    settings.enable_native_reminders = False
    yield
    settings.live_recovery_enabled = orig_live
    settings.enable_native_reminders = orig_reminders


def _mock_order_gateway(amount_paise: int, receipt: str, notes: dict) -> dict:
    return {
        "id": f"order_mock_{receipt}",
        "entity": "order",
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "status": "created",
        "notes": notes,
    }


def _mock_link_gateway(amount_paise: int, description: str, notes: dict, reminder_enable: bool = False, expire_by=None) -> dict:
    return {
        "id": f"plink_mock_{notes.get('case_id')}",
        "entity": "payment_link",
        "amount": amount_paise,
        "currency": "INR",
        "short_url": "https://rzp.io/i/mockLink123",
        "status": "created",
        "reminder_enable": reminder_enable,
        "notes": notes,
    }


def _mock_fetch_payment(payment_id: str) -> dict:
    return {
        "id": payment_id,
        "entity": "payment",
        "amount": 250000,
        "currency": "INR",
        "status": "captured",
        "order_id": "order_mock_123",
        "fee": 5000,
        "captured": True,
    }


def test_live_vs_lab_menu(factory):
    """B2.2: Live track drops SWITCH_GATEWAY; lab track retains full simulated menu."""
    db = factory()
    try:
        cust = Customer(id="CUS-MENU-1", name="Test User", email="menu@example.com")
        pay = Payment(id="PAY-MENU-1", customer_id=cust.id, amount=2500.0, gateway="RAZORPAY", status="FAILED")

        # 1. Live case: only RETRY_PAYMENT and CREATE_PAYMENT_LINK
        live_case = RevenueRiskCase(
            id="RR-LIVE-1",
            customer_id=cust.id,
            payment_id=pay.id,
            case_type=CaseType.FAILED_PAYMENT.value,
            origin="live",
            amount_at_risk=2500.0,
            status=CaseStatus.DETECTED.value,
        )
        db.add_all([cust, pay, live_case])
        db.commit()

        live_menu = allowed_menu(db, live_case, {"payment_id": pay.id})
        live_actions = [item["action"] for item in live_menu]
        assert InterventionType.RETRY_PAYMENT.value in live_actions
        assert InterventionType.CREATE_PAYMENT_LINK.value in live_actions
        assert InterventionType.SWITCH_GATEWAY.value not in live_actions  # Dropped on live path!

        # 2. Lab case: retains simulated SWITCH_GATEWAY
        lab_case = RevenueRiskCase(
            id="RR-LAB-1",
            customer_id=cust.id,
            payment_id=pay.id,
            case_type=CaseType.FAILED_PAYMENT.value,
            origin="lab",
            amount_at_risk=2500.0,
            status=CaseStatus.DETECTED.value,
        )
        db.add(lab_case)
        db.commit()

        lab_menu = allowed_menu(db, lab_case, {"payment_id": pay.id})
        lab_actions = [item["action"] for item in lab_menu]
        assert InterventionType.SWITCH_GATEWAY.value in lab_actions
    finally:
        db.close()


def test_execute_tool_live_dispatch_and_provider_objects(factory, monkeypatch):
    """B2.1, B2.3: Live case execution creates real Razorpay objects and logs to provider_objects."""
    monkeypatch.setattr(razorpay_service, "_create_order_on_gateway", _mock_order_gateway)
    monkeypatch.setattr(razorpay_service, "_create_payment_link_on_gateway", _mock_link_gateway)

    db = factory()
    try:
        cust = Customer(id="CUS-LIVE-1", name="Aarav Gupta", email="aarav@example.com", origin="live")
        pay = Payment(id="PAY-LIVE-1", customer_id=cust.id, amount=4000.0, gateway="RAZORPAY", status="FAILED", origin="live")
        case = RevenueRiskCase(
            id="RR-LIVE-ACT-1",
            customer_id=cust.id,
            payment_id=pay.id,
            case_type=CaseType.FAILED_PAYMENT.value,
            origin="live",
            amount_at_risk=4000.0,
            attempt_count=0,
            status=CaseStatus.PLANNING.value,
        )
        db.add_all([cust, pay, case])
        db.commit()

        config = {"configurable": {"thread_id": case.id, "session_factory": factory}}

        # 1. Execute RETRY_PAYMENT on live case
        state1 = {
            "case_id": case.id,
            "chosen_action": InterventionType.RETRY_PAYMENT.value,
            "context": {"payment_id": pay.id},
        }
        res1 = execute_tool(state1, config)
        assert res1["tool_result"]["success"] is True
        assert res1["attempt"] == 1
        assert "order_mock" in res1["tool_result"]["data"]["order_id"]

        # Assert provider_objects row created
        pobj1 = db.query(ProviderObject).filter(ProviderObject.case_id == case.id, ProviderObject.object_type == "order").first()
        assert pobj1 is not None
        assert pobj1.amount_paise == 400000

        # 2. Execute CREATE_PAYMENT_LINK on live case
        state2 = {
            "case_id": case.id,
            "chosen_action": InterventionType.CREATE_PAYMENT_LINK.value,
            "context": {"payment_id": pay.id},
        }
        res2 = execute_tool(state2, config)
        assert res2["tool_result"]["success"] is True
        assert res2["attempt"] == 2
        assert "plink_mock" in res2["tool_result"]["data"]["payment_link_id"]

        # Assert provider_objects row created
        pobj2 = db.query(ProviderObject).filter(ProviderObject.case_id == case.id, ProviderObject.object_type == "payment_link").first()
        assert pobj2 is not None

        # B2.2 Agreement: attempt_count (2) matches count of provider_objects rows (2)
        db.refresh(case)
        assert case.attempt_count == 2
        provider_obj_count = db.query(ProviderObject).filter(ProviderObject.case_id == case.id).count()
        assert case.attempt_count == provider_obj_count
    finally:
        db.close()


def test_execute_tool_lab_dispatch_uses_oracle(factory):
    """B2.3: Lab case (origin='lab') continues using simulation oracle without touching provider_objects."""
    db = factory()
    try:
        from app.models.metric import GatewayMetric

        gw = GatewayMetric(id="GWM-00001", gateway_name="RAZORPAY", success_rate=0.9, latency_ms=120.0, health_status="HEALTHY")
        cust = Customer(id="CUS-LAB-1", name="Sim User", email="sim@sim.invalid", origin="lab", intent_score=1.0)
        pay = Payment(
            id="PAY-LAB-1",
            customer_id=cust.id,
            amount=1000.0,
            gateway="RAZORPAY",
            status="FAILED",
            origin="lab",
            attempt_count=0,
            method_health=1.0,
            recovery_roll=0.1,  # Guaranteed success in sim (0.1 < 0.9)
        )
        case = RevenueRiskCase(
            id="RR-LAB-ACT-1",
            customer_id=cust.id,
            payment_id=pay.id,
            case_type=CaseType.FAILED_PAYMENT.value,
            origin="lab",
            amount_at_risk=1000.0,
            attempt_count=0,
            status=CaseStatus.PLANNING.value,
        )
        db.add_all([gw, cust, pay, case])
        db.commit()

        config = {"configurable": {"thread_id": case.id, "session_factory": factory}}
        state = {
            "case_id": case.id,
            "chosen_action": InterventionType.RETRY_PAYMENT.value,
            "context": {"payment_id": pay.id},
        }
        res = execute_tool(state, config)
        assert res["tool_result"]["success"] is True
        assert "roll=" in res["tool_result"]["detail"]  # Oracle detail signature

        # Lab case does NOT create rows in provider_objects
        pobj_count = db.query(ProviderObject).filter(ProviderObject.case_id == case.id).count()
        assert pobj_count == 0
    finally:
        db.close()


def test_native_reminders_guard_and_communication_recording(factory, monkeypatch):
    """Principle 7 & B2: Native reminders disabled by default; Communication row recorded when enabled."""
    monkeypatch.setattr(razorpay_service, "_create_payment_link_on_gateway", _mock_link_gateway)

    db = factory()
    try:
        cust = Customer(id="CUS-REM-1", name="Rohan Das", email="rohan@example.com", origin="live")
        pay = Payment(id="PAY-REM-1", customer_id=cust.id, amount=1200.0, gateway="RAZORPAY", status="FAILED", origin="live")
        case = RevenueRiskCase(
            id="RR-REM-1",
            customer_id=cust.id,
            payment_id=pay.id,
            case_type=CaseType.FAILED_PAYMENT.value,
            origin="live",
            amount_at_risk=1200.0,
            status=CaseStatus.DETECTED.value,
        )
        db.add_all([cust, pay, case])
        db.commit()

        # 1. Default: enable_native_reminders is False -> 0 Communication rows
        settings.enable_native_reminders = False
        res1 = razorpay_service.create_payment_link_for_case(db, case_id=case.id)
        assert res1["status"] == "created"
        comm_count = db.query(Communication).filter(Communication.case_id == case.id).count()
        assert comm_count == 0

        # 2. Opt-in: enable_native_reminders is True -> 1 Communication row recorded
        settings.enable_native_reminders = True
        res2 = razorpay_service.create_payment_link_for_case(db, case_id=case.id)
        assert res2["status"] == "created"
        comm = db.query(Communication).filter(Communication.case_id == case.id).first()
        assert comm is not None
        assert "native payment link reminder enabled" in comm.content
    finally:
        db.close()


def test_fetch_payment_seam(monkeypatch):
    """B2.1: fetch_payment reads payment status and fee from gateway boundary."""
    monkeypatch.setattr(razorpay_service, "_fetch_payment_on_gateway", _mock_fetch_payment)

    res = razorpay_service.fetch_payment("pay_test_xyz")
    assert res["id"] == "pay_test_xyz"
    assert res["captured"] is True
    assert res["fee"] == 5000
