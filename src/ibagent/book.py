"""Engine-owned book (Phase 3): positions with lots, stops, targets, sleeve tags, entry
dates, high-water marks per sleeve and total, settled/unsettled cash, pending withdrawals.
Persisted as JSON in data/book.json; reconciled against the broker every fast loop.
Mismatch -> freeze (never auto-corrected)."""


class Book:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Phase 3: book.py")
