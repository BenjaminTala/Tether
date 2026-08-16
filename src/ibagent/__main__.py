"""`python -m ibagent ...` — used by the Task Scheduler entries (windows/install_tasks.ps1)."""
import sys

from ibagent.cli import main

sys.exit(main())
