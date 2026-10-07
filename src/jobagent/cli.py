"""Command-line interface: the ``jobagent`` console script.

Subcommands:

- ``scout``: read postings JSONL, run scout filters, write accepted JSONL
- ``digest``: read postings JSONL, write the daily digest markdown
- ``ats``: score a JD JSON file (jd_text, required, preferred, candidate_skills)
- ``resume-check``: check a resume text file against truthfulness guards
- ``submit``: dry-run demo of the submitter state machine
- ``track``: add / status / list applications in the SQLite ledger
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobagent import __version__
from jobagent import ats as ats_mod
from jobagent import digest as digest_mod
from jobagent import preparer as preparer_mod
from jobagent import scout as scout_mod
from jobagent import submitter as submitter_mod
from jobagent import tracker as tracker_mod
from jobagent.config import load_config, resolve_project_root
from jobagent.models import Application, ApplicationStatus, JobPosting


def _read_jsonl(path: Path) -> list[dict]:
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# scout
# ---------------------------------------------------------------------------
def cmd_scout(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    raw = _read_jsonl(Path(args.input))
    seen: set[tuple[str, str, str]] = set()
    if args.seen:
        for item in _read_jsonl(Path(args.seen)):
            seen.add(scout_mod.posting_key(JobPosting.from_dict(item)))

    accepted: list[dict] = []
    for item in raw:
        posting = JobPosting.from_dict(item)
        evaluation = scout_mod.evaluate_posting(posting, cfg)
        if not evaluation.accepted:
            if args.verbose:
                print(
                    f"REJECT {posting.company} — {posting.title}: "
                    f"{'; '.join(evaluation.reasons)}",
                    file=sys.stderr,
                )
            continue
        key = scout_mod.posting_key(posting)
        if key in seen:
            if args.verbose:
                print(
                    f"DUPE   {posting.company} — {posting.title}", file=sys.stderr
                )
            continue
        seen.add(key)
        accepted.append(posting.to_dict())

    out = Path(args.output) if args.output else None
    if out:
        _write_jsonl(out, accepted)
    else:
        for item in accepted:
            print(json.dumps(item, ensure_ascii=False))
    print(f"scout: {len(accepted)}/{len(raw)} postings accepted", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------
def cmd_digest(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    postings = [JobPosting.from_dict(i) for i in _read_jsonl(Path(args.input))]
    text = digest_mod.build_digest(postings, cfg, date=args.date or "")
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------------------
# ats
# ---------------------------------------------------------------------------
def cmd_ats(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = ats_mod.score_jd(
        payload.get("jd_text", ""),
        payload.get("required", []),
        payload.get("preferred", []),
        payload.get("candidate_skills", []),
        cfg,
    )
    print(f"score: {result.score}/100  band: {result.band}")
    print(f"matched ({len(result.matched)}): {', '.join(result.matched) or '—'}")
    print(f"missed  ({len(result.missed)}): {', '.join(result.missed) or '—'}")
    for note in result.notes:
        print(f"note: {note}")
    return 0


# ---------------------------------------------------------------------------
# resume-check
# ---------------------------------------------------------------------------
def cmd_resume_check(args: argparse.Namespace) -> int:
    text = Path(args.input).read_text(encoding="utf-8")
    violations = preparer_mod.check_resume_text(text)
    if not violations:
        print("PASS: no truthfulness violations found.")
        return 0
    print(f"FAIL: {len(violations)} violation(s):")
    for v in violations:
        print(f"  - {v}")
    return 1


# ---------------------------------------------------------------------------
# submit (dry-run demo)
# ---------------------------------------------------------------------------
def cmd_submit(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    app = Application(
        company=args.company or "Acme Corp",
        title=args.title or "Data Analyst",
        url=args.url or "https://example.com/jobs/123",
        track="primary",
        ats_score=82,
    )
    plan = submitter_mod.FormFillPlan(
        application_id=None,
        fields=[
            submitter_mod.FormField(
                "full_name", submitter_mod.FieldSource.USER_CONFIG,
                value=cfg.personal.full_name,
            ),
            submitter_mod.FormField(
                "email", submitter_mod.FieldSource.USER_CONFIG,
                value=cfg.personal.email,
            ),
            submitter_mod.FormField(
                "phone", submitter_mod.FieldSource.USER_CONFIG,
                value=cfg.personal.phone,
            ),
            submitter_mod.FormField(
                "work_authorization", submitter_mod.FieldSource.SIMPLIFY,
                value="Authorized to work in the U.S.",
            ),
            submitter_mod.FormField(
                "cover_letter", submitter_mod.FieldSource.NEEDS_USER,
            ),
            submitter_mod.FormField(
                "privacy_consent", submitter_mod.FieldSource.NEEDS_USER,
                is_legal=True, legal_key="privacy_consent",
            ),
        ],
    )
    gate = submitter_mod.ReviewGate(
        cfg=cfg,
        captcha_policy=submitter_mod.CaptchaPolicy(cfg.captcha_policy),
    )
    report, allowed, reason = submitter_mod.run_submission_flow(
        app, plan, submitter_mod.DryRunFiller(), gate
    )

    print(f"application: {app.company} — {app.title}")
    print(f"status: {app.status.value}")
    print(f"filled: {', '.join(report.filled_fields) or '—'}")
    print(f"skipped: {', '.join(report.skipped_fields) or '—'}")
    for note in report.notes:
        print(f"note: {note}")
    print(f"auto-submit allowed: {allowed} ({reason})")
    print("dry-run: no browser was touched and nothing was submitted.")
    return 0


# ---------------------------------------------------------------------------
# track
# ---------------------------------------------------------------------------
def _default_db(root: Path) -> Path:
    return root / "applications.db"


def cmd_track(args: argparse.Namespace) -> int:
    root = Path(args.root)
    db = Path(args.db) if args.db else _default_db(root)
    with tracker_mod.Tracker(db) as t:
        if args.track_cmd == "add":
            app = Application(
                company=args.company,
                title=args.title,
                url=args.url or "",
                track=args.track_name or "",
                ats_score=args.ats_score,
                notes=args.notes or "",
            )
            app_id = t.add(app)
            print(f"added application id={app_id}")
        elif args.track_cmd == "status":
            app = t.set_status(args.id, ApplicationStatus(args.status))
            print(f"id={app.id} -> {app.status.value}")
        elif args.track_cmd == "list":
            status = ApplicationStatus(args.status) if args.status else None
            apps = t.list(status)
            if not apps:
                print("no applications")
            for a in apps:
                print(
                    f"[{a.id}] {a.status.value:16} {a.company} — {a.title}"
                    f"  (ats={a.ats_score})"
                )
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jobagent", description="Deterministic job-search pipeline CLI"
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--root",
        default=str(resolve_project_root()),
        help="project root (config/, default: repo root)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scout", help="filter postings JSONL -> accepted JSONL")
    s.add_argument("input", help="input postings JSONL")
    s.add_argument("-o", "--output", help="output JSONL (default: stdout)")
    s.add_argument("--seen", help="JSONL of already-seen postings for dedupe")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_scout)

    d = sub.add_parser("digest", help="postings JSONL -> daily digest markdown")
    d.add_argument("input", help="input postings JSONL")
    d.add_argument("-o", "--output", help="output markdown file (default: stdout)")
    d.add_argument("--date", default="", help="digest date label, e.g. 2026-10-07")
    d.set_defaults(func=cmd_digest)

    a = sub.add_parser("ats", help="score a JD JSON file")
    a.add_argument("input", help="JSON with jd_text/required/preferred/candidate_skills")
    a.set_defaults(func=cmd_ats)

    r = sub.add_parser("resume-check", help="check resume text for truthfulness violations")
    r.add_argument("input", help="resume text file")
    r.set_defaults(func=cmd_resume_check)

    b = sub.add_parser("submit", help="dry-run demo of the submitter state machine")
    b.add_argument("--company", default="")
    b.add_argument("--title", default="")
    b.add_argument("--url", default="")
    b.set_defaults(func=cmd_submit)

    t = sub.add_parser("track", help="application ledger")
    t.add_argument("--db", default="", help="sqlite db path (default: <root>/applications.db)")
    tsub = t.add_subparsers(dest="track_cmd", required=True)

    ta = tsub.add_parser("add", help="add an application")
    ta.add_argument("--company", required=True)
    ta.add_argument("--title", required=True)
    ta.add_argument("--url", default="")
    ta.add_argument("--track-name", default="")
    ta.add_argument("--ats-score", type=int, default=None)
    ta.add_argument("--notes", default="")
    ta.set_defaults(func=cmd_track)

    ts = tsub.add_parser("status", help="transition an application status")
    ts.add_argument("id", type=int)
    ts.add_argument("status", choices=[s.value for s in ApplicationStatus])
    ts.set_defaults(func=cmd_track)

    tl = tsub.add_parser("list", help="list applications")
    tl.add_argument("--status", choices=[s.value for s in ApplicationStatus], default=None)
    tl.set_defaults(func=cmd_track)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
