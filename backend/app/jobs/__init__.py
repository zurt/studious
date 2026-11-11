"""In-process job queue. `manager` is the app-wide instance.

Layout: `manager.py` holds the queue, lifecycle and dispatch; each job
type's runner is a mixin in its own module (`pages`, `regions`,
`breakdown`, `bulk`, `exercise`, `grammar_guide`); `_common.py` holds
shared helpers.
"""
from .manager import JobManager, manager

__all__ = ["JobManager", "manager"]
