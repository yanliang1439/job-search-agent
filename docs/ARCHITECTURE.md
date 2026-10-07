# Architecture: from markdown agents to code

The original pipeline was four markdown instruction documents plus ad-hoc
agent runs:

| # | Markdown agent | Instruction doc | Role |
|---|---|---|---|
| 1 | 猎手 (Scout) | `scout_brief.md` | daily scan, filter, dedupe, JD-verify, daily digest |
| 2 | 投递手 (Preparer) | `preparer_brief.md` | JD intake, ATS score, tailored resume, cover letter, tracker |
| 3 | Submitter | (new, Hermes-style) | browser form filling with human review |
| 4 | Networker | (outreach drafts) | referral targets + cold messages — NOT ported (outreach copy is a writing task, not a rules engine) |

## How the modules map

```
scout_brief.md  ──rules──>  jobagent/scout.py      (filters)
                   │         jobagent/digest.py     (daily report)
                   │         config/keywords.yaml   (track keywords)
                   │         config/preferences.example.yaml (windows, caps, blacklists)
                   ▼
preparer_brief.md ──rules──> jobagent/ats.py        (0-100 scoring + bands)
                             jobagent/preparer.py   (resume truthfulness guards)
                             jobagent/models.py     (ATSResult)

new submitter   ──rules──>  jobagent/submitter.py  (FormFillPlan, ReviewGate,
                             FormFillerAdapter, DryRunFiller, PlaywrightFiller stub)
                             jobagent/models.py     (Application state machine)

Excel tracker   ──schema─>  jobagent/tracker.py    (SQLite applications table)
```

## Key design decisions

1. **Deterministic over clever.** `ats.score_jd` is a documented weighted
   heuristic, not an LLM call, so the same JD + skill bank always yields the
   same score. "Strong match" (used by the 3–5yr / Mid-IC rules) is defined
   as ≥50% of the track's keywords appearing in the posting
   (`scout.STRONG_MATCH_RATIO`).
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

- Resume LaTeX generation and cover-letter writing (writing tasks; the
  truthfulness guards in `preparer.py` are the codifiable part).
- Real browser automation (`PlaywrightFiller` is a stub by design).
- The networker/outreach agent (no stable rules to encode).
- The Simplify-profile lookup (needs a live browser session; the
  `FieldSource.SIMPLIFY` provenance slot is reserved in `FormFillPlan`).
