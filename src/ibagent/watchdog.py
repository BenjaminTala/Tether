"""Watchdog (Phase 6): tiny separate process run by Task Scheduler every 5 min. Reads the
heartbeat file; if stale > alerts.heartbeat_stale_minutes, alerts you. Never touches the broker."""


def main(*args, **kwargs):
    raise NotImplementedError("Phase 6: watchdog.py")
