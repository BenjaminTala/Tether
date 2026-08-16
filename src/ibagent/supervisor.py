"""Supervisor (Phase 6): the single long-running process. APScheduler jobs: fast loop (RTH),
slow loop, news poll, weekly review, daily check, daily report, event gate. Heartbeat file,
kill-switch check, IB reconnects, graceful degradation when Claude is unavailable."""


def main(*args, **kwargs):
    raise NotImplementedError("Phase 6: supervisor.py")
