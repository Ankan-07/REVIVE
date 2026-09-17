"""Simulation package for eval benchmarks (Phase E2).

Registers simulation oracles into app.agent.menu dynamically during lab eval runs,
ensuring live code paths never directly import or depend on simulation modules.
"""
def _register_sim_oracles() -> None:
    try:
        from app.agent.menu import register_simulation_oracle
        from app.schemas.enums import InterventionType
        from app.simulation import checkout_sim, invoice_sim, payment_sim

        register_simulation_oracle(InterventionType.RETRY_PAYMENT.value, payment_sim.simulate_payment)
        register_simulation_oracle(InterventionType.SWITCH_GATEWAY.value, payment_sim.simulate_payment)
        register_simulation_oracle(InterventionType.CREATE_PAYMENT_LINK.value, payment_sim.simulate_payment)
        register_simulation_oracle(InterventionType.SEND_DISCOUNT_MESSAGE.value, checkout_sim.simulate_checkout_action)
        register_simulation_oracle(InterventionType.SEND_REMINDER.value, checkout_sim.simulate_checkout_action)
        register_simulation_oracle(InterventionType.OFFER_PAYMENT_PLAN.value, checkout_sim.simulate_checkout_action)
        register_simulation_oracle(InterventionType.VERIFY_PROMISE.value, invoice_sim.simulate_invoice_action)
    except Exception:
        pass


_register_sim_oracles()
