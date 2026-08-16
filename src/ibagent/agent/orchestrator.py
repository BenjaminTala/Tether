"""Agent orchestrator (Phase 5): daily invocation cap, run -> parse_decision -> on invalid,
one retry with the errors -> on failure/unavailable, HOLD + alert -> journal everything ->
hand the Decision to risk.plan_orders."""


def run_cycle(*args, **kwargs):
    raise NotImplementedError("Phase 5: agent/orchestrator.py")
