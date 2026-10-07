"""jobagent: a deterministic, testable job-search pipeline.

Modules mirror the four pipeline stages of the original markdown-based
multi-agent workflow:

- :mod:`jobagent.scout` — scan/filter/dedupe job postings (was: scout agent)
- :mod:`jobagent.digest` — build the daily digest with a recommendation zone
  and a pending-verification zone (was: scout agent's daily report)
- :mod:`jobagent.ats` — deterministic JD scoring (was: preparer agent's ATS step)
- :mod:`jobagent.preparer` — resume truthfulness guards (was: preparer agent)
- :mod:`jobagent.submitter` — human-in-the-loop form filling in the Hermes
  style: the agent fills everything, the human always owns the final click
  and every legal checkbox (was: submitter agent)
- :mod:`jobagent.tracker` — SQLite application ledger (was: Excel tracker)
- :mod:`jobagent.config` / :mod:`jobagent.models` — configuration and data model
"""

__version__ = "0.1.0"

from jobagent.models import ATSResult, Application, JobPosting

__all__ = ["ATSResult", "Application", "JobPosting", "__version__"]
