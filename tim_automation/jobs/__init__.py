"""Jobs: named lists of tasks that run one after another in the TiM ERP browser. See tasks.py for task
types, store.py for how jobs are saved and runner.py for how they run."""
from tim_automation.jobs.runner import JobError, JobRunner

__all__ = ["JobError", "JobRunner"]
