"""ATS: deterministic heuristic JD scoring (0-100).

The preparer brief calls for a 0-100 ATS score with Matched / Missed skill
lists. The original markdown workflow did this by judgement; this module
makes it reproducible with a documented heuristic:

- required skills (from the JD intake) weigh most,
- nice-to-have / preferred skills weigh less,
- tool mentions that overlap the candidate's confirmed skill bank weigh less,
- a penalty applies when hard requirements are missed.

Bands mirror the brief:

- >= priority_threshold (85): apply today, deep customization
- >= recommend_threshold (75): apply, customize and review
- >= low_priority_threshold (60): low priority, only if user insists or the
  cost of applying is trivial
- below: normally do not apply
"""

from __future__ import annotations

import re

from jobagent.config import Config
from jobagent.models import ATSResult

#: Heuristic weights for the three requirement buckets.
W_REQUIRED = 3.0
W_PREFERRED = 1.5
W_TOOLS = 1.0
#: Penalty multiplier applied per missed hard requirement.
MISS_PENALTY = 6.0


def _normalize(text: str) -> str:
    """Lowercase and collapse punctuation to spaces (keeps + # / for skills)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9+#/ ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _mentions(skill: str, normalized_text: str) -> bool:
    """Check whether a skill phrase appears in normalized text (word-boundary)."""
    needle = _normalize(skill)
    if not needle:
        return False
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return re.search(pattern, normalized_text) is not None


def score_jd(
    jd_text: str,
    required: list[str],
    preferred: list[str] | None = None,
    candidate_skills: list[str] | None = None,
    cfg: Config | None = None,
) -> ATSResult:
    """Score a JD deterministically.

    Args:
        jd_text: full job description text.
        required: hard requirements extracted from the JD intake.
        preferred: nice-to-have / preferred items from the JD intake.
        candidate_skills: the candidate's confirmed skill bank. A required
            skill counts as matched only when the candidate has it.
        cfg: configuration (for band thresholds).

    Returns:
        ATSResult with score, band, matched/missed lists.
    """
    cfg = cfg or Config()
    preferred = preferred or []
    candidate_skills = candidate_skills or []
    norm_jd = _normalize(jd_text)
    norm_bank = {_normalize(s) for s in candidate_skills}

    matched: list[str] = []
    missed: list[str] = []
    notes: list[str] = []
    earned = 0.0
    possible = 0.0

    def has_candidate(skill: str) -> bool:
        needle = _normalize(skill)
        return any(needle in bank or bank in needle for bank in norm_bank if needle)

    for skill in required:
        possible += W_REQUIRED
        if _mentions(skill, norm_jd) and has_candidate(skill):
            matched.append(skill)
            earned += W_REQUIRED
        else:
            missed.append(skill)

    for skill in preferred:
        possible += W_PREFERRED
        if _mentions(skill, norm_jd) and has_candidate(skill):
            matched.append(skill)
            earned += W_PREFERRED
        else:
            missed.append(skill)

    score = (earned / possible * 100.0) if possible else 0.0
    score -= MISS_PENALTY * len([s for s in missed if s in required])
    score = max(0.0, min(100.0, score))
    final = int(round(score))

    if final >= cfg.ats.priority_threshold:
        band = "priority"
        notes.append(">=85: apply today; deep customization; compare score before/after.")
    elif final >= cfg.ats.recommend_threshold:
        band = "recommend"
        notes.append("75-84: apply; customize and review.")
    elif final >= cfg.ats.low_priority_threshold:
        band = "low_priority"
        notes.append("60-74: low priority; only if the user insists or cost is trivial.")
    else:
        band = "skip"
        notes.append("<60: normally do not apply; explain why to the user.")

    return ATSResult(
        score=final, band=band, matched=matched, missed=missed, notes=notes
    )
