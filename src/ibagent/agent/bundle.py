"""Context bundle builder (Phase 5): writes the per-run directory the model may read:
mandate_excerpt.md, portfolio.json, prices.json (ATR, momentum table), news_digest.md,
journal_tail.md (last decisions + outcomes), decision_schema.json, TASK.md. Nothing else."""


def build_bundle(*args, **kwargs):
    raise NotImplementedError("Phase 5: agent/bundle.py")
