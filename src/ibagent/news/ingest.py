"""News ingestion (Phase 4): SEC EDGAR (8-K/10-Q/10-K per held/watched CIK), RSS feeds,
IBKR news providers via the API. Deduped, timestamped, stored as untrusted text with source URL."""


def poll(*args, **kwargs):
    raise NotImplementedError("Phase 4: news/ingest.py")
