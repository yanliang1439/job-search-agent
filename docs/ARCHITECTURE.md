# Architecture

## Modules

```
config/*.example.yaml ──templates──> user copies to gitignored
                                     preferences.yaml / keywords.yaml / user.yaml
                                          │
                                          ▼
jobagent/config.py ──loads──> Config (all rules are user-tunable)
                                          │
        ┌─────────────┬─────────────┬─────┴───────┬──────────────┐
        ▼             ▼             ▼             ▼              ▼
   scout.py      digest.py      ats.py     preparer.py    submitter.py
   (filters)   (daily report) (0-100     (resume         (FormFillPlan,
                             scoring)    truthfulness     ReviewGate,
                                         guards)         state machine)
                                                        │
                                                        ▼
                                                   tracker.py
                                              (SQLite applications)
```

`jobagent/models.py` holds the typed dataclasses (`JobPosting`, `ATSResult`,
`Application`); `jobagent/cli.py` wires everything to the `jobagent`
command.

## Key design decisions

1. **Deterministic over clever.** `ats.score_jd` is a documented weighted
   heuristic, not an LLM call, so the same JD + skill bank always yields the
   same score. "Strong match" (used by the 3–5yr / Mid-IC rules) is defined
   as a configurable fraction of the track's keywords appearing in the
   posting (`levels.strong_match_ratio`, default 0.5).
2. **Fail closed.** Unparseable posting dates are not fresh; unverified
   postings never enter the recommendation zone; unknown legal items block
   auto-submit.
3. **Human owns submission.** `ReviewGate.can_auto_submit` returns
   `(False, reason)` whenever a required field is unresolved or any legal
   item (privacy consent, arbitration, background check, drug test,
   non-compete, attestation, e-signature) lacks explicit per-item consent.
   `run_submission_flow` never clicks submit — it only advances the status
   to `READY_TO_SUBMIT` or `AWAITING_REVIEW`.
4. **PII boundary.** `config.py` loads personal data exclusively from the
   gitignored `config/user.yaml` or `JOBAGENT_*` env vars. Everything
   committed uses placeholders.
5. **Stdlib only.** No third-party runtime dependencies; the YAML subset
   parser in `config.py` covers the config files' needs. `pytest` is the
   only dev dependency.

## What was intentionally left out (v1)

- Resume generation and cover-letter writing (writing tasks; the
  truthfulness guards in `preparer.py` are the codifiable part).
- Real browser automation (`PlaywrightFiller` is a stub by design).
- Job-board scrapers (`scout` consumes postings JSONL; collectors are
  a separate concern).
- The Simplify-profile lookup (needs a live browser session; the
  `FieldSource.SIMPLIFY` provenance slot is reserved in `FormFillPlan`).
