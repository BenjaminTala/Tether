"""Deterministic materiality scoring (Phase 4): keyword/entity rules per held/watched symbol
(earnings, guidance, FDA, M&A, downgrade, SEC filing types) + magnitude of the same-day price
move. Produces the digest for daily runs and the event-trigger gate (max_per_day, cooldown)."""


def score(*args, **kwargs):
    raise NotImplementedError("Phase 4: news/scoring.py")
