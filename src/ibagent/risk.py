"""Risk layer (Phase 3): the only path from a Decision to orders.

  Decision -> semantic validation vs mandate (whitelist, sleeve caps, active weight cap x
  risk_multiplier, no averaging down, cooldowns, stops never widened, fee/min-order floors,
  settled-cash constraint, weekly turnover/new-position caps, circuit breakers)
           -> TargetBook (qty, stop, target per position)
           -> list[OrderRequest] (exits first, then entries), all RTH marketable-limit.
Pure functions over (mandate, book, prices, decision) so it is fully unit-testable.
"""


def plan_orders(*args, **kwargs):
    raise NotImplementedError("Phase 3: risk.py")
