"""Digest: build the daily job report.

Rules from the scout brief:

- Only verified=True postings enter the recommendation zone. Anything
  unverified goes to a separate pending-verification section with just the
  title and the reason it could not be verified. It takes NO digest slots.
- Recommendation zone is capped at cfg.digest.max_entries (default 20).
- Every track with new verified postings shows at least
  cfg.digest.min_per_track entries (default 3); fewer available means
  show what there is.
- Remaining slots are filled in track priority order:
  Primary > Secondary > Extended > Selective.
- Anything beyond the cap is reported as an overflow count.

Output is a markdown string.
"""

from __future__ import annotations

from jobagent.config import Config
from jobagent.models import JobPosting


def _sort_key(posting):
    # type: (JobPosting) -> tuple
    return (posting.company.lower(), posting.title.lower(), posting.posted_at)


def build_digest(postings, cfg, date=""):
    # type: (list, Config, str) -> str
    """Build the daily digest markdown from scouted postings."""
    verified = sorted([p for p in postings if p.verified], key=_sort_key)
    pending = sorted([p for p in postings if not p.verified], key=_sort_key)

    rules = cfg.digest
    cap = rules.max_entries
    track_order = [t for t in rules.track_order if t]

    by_track = {t: [] for t in track_order}
    for p in verified:
        track = p.track if p.track in by_track else None
        if track is None:
            track = track_order[-1] if track_order else "extended"
        by_track.setdefault(track, []).append(p)

    # Phase 1: per-track minimums.
    chosen = []
    leftovers = []
    for track in track_order:
        bucket = by_track.get(track, [])
        take = min(rules.min_per_track, len(bucket))
        chosen.extend(bucket[:take])
        leftovers.extend(bucket[take:])

    # Phase 2: fill remaining slots in track priority order.
    remaining = cap - len(chosen)
    extra = []
    if remaining > 0:
        ordered_leftovers = []
        for track in track_order:
            ordered_leftovers.extend([p for p in leftovers if p.track == track])
        extra = ordered_leftovers[:remaining]
    chosen.extend(extra)
    overflow = len(leftovers) - len(extra)

    lines = []
    lines.append("# Daily Job Digest %s" % date if date else "# Daily Job Digest")
    lines.append("")
    lines.append("## Recommendation zone (JD-verified)")
    lines.append("")

    if not chosen:
        lines.append("No new postings today.")
        lines.append("")
    else:
        for track in track_order:
            entries = [p for p in chosen if p.track == track]
            if not entries:
                continue
            lines.append("### %s (%d)" % (track.capitalize(), len(entries)))
            lines.append("")
            for i, p in enumerate(entries, 1):
                flag_str = " [" + ", ".join(p.flags) + "]" if p.flags else ""
                reason = " - %s" % p.match_reason if p.match_reason else ""
                loc = " | %s" % p.location if p.location else ""
                lines.append(
                    "%d. **%s** - %s%s%s\n   Link: %s%s"
                    % (i, p.company, p.title, loc, flag_str, p.url, reason)
                )
            lines.append("")

    if overflow:
        lines.append(
            "_%d more verified postings exceed the %d-entry cap; see the full list._"
            % (overflow, cap)
        )
        lines.append("")

    lines.append("## Pending verification (takes no slots)")
    lines.append("")
    if not pending:
        lines.append("None.")
    else:
        for p in pending:
            note = p.verification_note or "not verified"
            lines.append("- %s - %s: %s" % (p.company, p.title, note))
    lines.append("")

    return "\n".join(lines)
