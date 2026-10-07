"""Scout: scan, filter, and dedupe job postings.

Implements the filter rules from the scout brief:

- freshness: job boards 24h, university career pages 14 days
- track classification by keyword
- level judgement: entry/junior/associate/I/II accepted; 0-3 years accepted;
  3-5 years and Mid IC only on strong match; Senior/Staff/Principal and
  people-management roles excluded; hard "0-2yr / new-grad only" junior
  postings accepted with a ``caution_overqualified`` flag
- location: on-site/hybrid must be inside the configured region
  (``region_markers``) with a reasonable commute from home_base; remote
  accepted; clearly infeasible excluded
- staffing agencies and pre-sales titles excluded
- hard filters: citizenship/clearance requirements, heavy SWE/MLE production
  engineering roles

Note on "strong match": the brief reserves 3-5yr and Mid-IC postings for
strong matches. Here a posting is a strong match when at least
``cfg.levels.strong_match_ratio`` (default 0.5) of its track keywords appear
in the posting text. This is a heuristic approximation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

from jobagent.config import Config
from jobagent.models import JobPosting

_PEOPLE_MGMT = re.compile(
    r"\b(manage|lead|mentor|coach)\b.{0,40}\b(team|direct reports|reports|staff)\b"
    r"|\bpeople\s+manager\b|\bmanagement\s+experience\b|\blead\s+a\s+team\b",
    re.IGNORECASE,
)

_YEARS_PATTERNS = [
    # "3-5 years", "3+ years", "minimum of 3 years", "3 years of experience"
    re.compile(r"(\d+)\s*[-–—]\s*(\d+)\s*(?:\+)?\s*years?", re.IGNORECASE),
    re.compile(r"(\d+)\s*\+\s*years?", re.IGNORECASE),
    re.compile(
        r"(?:minimum|at least|requires?|with)\s+(?:of\s+)?(\d+)\s*(?:\+)?\s*years?",
        re.IGNORECASE,
    ),
    re.compile(r"(\d+)\s*years?\s+(?:of\s+)?(?:relevant\s+)?experience", re.IGNORECASE),
]

_NEW_GRAD_ONLY = re.compile(
    r"\bnew\s*grad(?:uate)?s?\s+only\b|\b0\s*[-–—]\s*2\s*years?\b"
    r"|\bentry[\s-]?level\s+only\b",
    re.IGNORECASE,
)

_SENIOR_WORDS = ("senior", "staff", "principal", "sr.", "sr ")
_CITIZEN_CLEARANCE = re.compile(
    r"\b(u\.?s\.?\s+citizen(?:ship)?|security\s+clearance|must\s+be\s+a\s+u\.?s\.?\s+citizen"
    r"|clearance\s+required|active\s+clearance)\b",
    re.IGNORECASE,
)
_HEAVY_SWE = re.compile(
    r"\b(production[\s-]grade|distributed\s+systems|microservices|kubernetes|"
    r"backend\s+engineer|software\s+development\s+engineer|"
    r"machine\s+learning\s+engineer|ml\s+engineer|"
    r"large[\s-]scale\s+(?:ml|machine\s+learning)|"
    r"model\s+(?:training|serving)\s+infrastructure)\b",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(r"\b(remote|work\s+from\s+home|wfh|fully\s+remote)\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
def parse_posted_at(value: str) -> datetime | None:
    """Parse an ISO date/datetime string; returns None when unparseable."""
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def is_fresh(
    posted_at: str,
    source: str,
    cfg: Config,
    now: datetime | None = None,
) -> bool:
    """Check the posting date against the freshness window.

    ``source == "university"`` gets the 14-day window; everything else gets
    the 24-hour job-board window. Unparseable dates fail closed (not fresh).
    """
    dt = parse_posted_at(posted_at)
    if dt is None:
        return False
    now = now or datetime.now(timezone.utc)
    age = now - dt
    if age.total_seconds() < 0:
        return False
    if source == "university":
        return age <= timedelta(days=cfg.university_freshness_days)
    return age <= timedelta(hours=cfg.job_board_freshness_hours)


# ---------------------------------------------------------------------------
# Track classification
# ---------------------------------------------------------------------------
def classify_track(title: str, description: str, cfg: Config) -> str | None:
    """Return the track name for a posting, or None when no track matches.

    Tracks are checked in ``cfg.track_order`` priority (primary first).
    """
    text = f"{title} {description}".lower()
    for track in cfg.track_order:
        keywords = cfg.tracks.get(track, [])
        if any(kw.lower() in text for kw in keywords):
            return track
    return None


def strong_match(title: str, description: str, track: str, cfg: Config) -> bool:
    """Heuristic "strong match": enough of the track keywords are hit."""
    keywords = cfg.tracks.get(track, [])
    if not keywords:
        return False
    text = f"{title} {description}".lower()
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return hits / len(keywords) >= cfg.levels.strong_match_ratio


# ---------------------------------------------------------------------------
# Level judgement
# ---------------------------------------------------------------------------
@dataclass
class LevelDecision:
    accepted: bool
    level: str = ""  # e.g. "junior", "3-5yr", "mid"
    flags: list[str] = field(default_factory=list)
    reason: str = ""


def _max_years_required(text: str) -> float | None:
    """Extract the largest years-of-experience requirement found, if any."""
    found: list[float] = []
    for pattern in _YEARS_PATTERNS:
        for m in pattern.finditer(text):
            groups = [g for g in m.groups() if g]
            for g in groups:
                try:
                    found.append(float(g))
                except ValueError:
                    pass
    return max(found) if found else None


def judge_level(
    title: str, description: str, cfg: Config, track: str = ""
) -> LevelDecision:
    """Judge whether the seniority level is in scope.

    Returns accepted/rejected with flags. New-grad-only hard "0-2yr" junior
    postings are accepted with a ``caution_overqualified`` flag per the brief.
    """
    text = f"{title} {description}"
    low = text.lower()
    rules = cfg.levels

    # Hard exclusions first.
    title_low = title.lower()
    if any(word in title_low for word in rules.excluded) or any(
        word in title_low for word in _SENIOR_WORDS
    ):
        if not any(
            ok in title_low
            for ok in ("junior", "associate", "entry", "analyst i", "analyst ii")
        ):
            return LevelDecision(False, level="senior", reason="senior-level title")
    if rules.exclude_people_management and _PEOPLE_MGMT.search(text):
        return LevelDecision(False, level="manager", reason="requires people management")

    # APM is overqualified-risky: accepted but flagged with caution.
    flags: list[str] = []
    if "associate product manager" in low:
        flags.append("caution_overqualified")

    # New-grad-only / hard 0-2yr: accepted but flagged.
    if rules.accept_new_grad_only_with_caution_flag and _NEW_GRAD_ONLY.search(text):
        flags.append("caution_overqualified")
        return LevelDecision(
            True, level="new-grad-only", flags=flags,
            reason="0-2yr/new-grad-only junior posting: overqualified screen-out risk",
        )

    # Explicit junior-family levels accepted outright.
    junior_markers = ("junior", "entry", "associate", "analyst i", "analyst ii",
                      "analyst 1", "analyst 2", " i ", " ii ")
    if any(m in f" {title_low} " for m in junior_markers):
        return LevelDecision(True, level="junior", flags=flags,
                             reason="junior-level title")

    years = _max_years_required(text)
    if years is not None:
        if years <= rules.outright_max_years:
            return LevelDecision(True, level=f"{years:g}yr", flags=flags,
                                 reason=f"requires {years:g} years: within outright range")
        if years <= rules.strong_match_max_years:
            if strong_match(title, description, track, cfg):
                return LevelDecision(
                    True, level=f"{years:g}yr", flags=flags + ["strong_match"],
                    reason=f"requires {years:g} years: strong match",
                )
            return LevelDecision(
                False, level=f"{years:g}yr",
                reason=f"requires {years:g} years without strong match",
            )
        return LevelDecision(
            False, level=f"{years:g}yr",
            reason=f"requires {years:g} years: above strong-match band",
        )

    # Mid IC without explicit years: only on strong match.
    if "mid" in title_low:
        if rules.mid_ic_strong_match_only:
            if strong_match(title, description, track, cfg):
                return LevelDecision(True, level="mid", flags=flags + ["strong_match"],
                                     reason="mid IC with strong match")
            return LevelDecision(False, level="mid",
                                 reason="mid IC without strong match")
        return LevelDecision(True, level="mid", flags=flags,
                             reason="mid IC accepted")

    # No level signal at all: accept but mark for user judgement.
    return LevelDecision(True, level="unknown", flags=flags + ["level_unclear"],
                         reason="no explicit level or years found")


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def location_ok(location: str, remote: bool, cfg: Config) -> tuple[bool, str]:
    """Check the location rule. Returns (ok, reason).

    Region matching is driven entirely by ``cfg.location``:
    ``region_markers`` (case-insensitive substrings) defines the acceptable
    region and ``reasonable_commute_cities`` the preferred cities inside it.
    When neither is configured, on-site postings are passed with a
    ``region_unconfigured`` note instead of being failed closed.
    """
    loc = cfg.location
    if remote or _REMOTE_RE.search(location):
        if not loc.remote_ok:
            return False, "remote not enabled"
        return True, "remote"
    low = location.lower()
    markers = [m.lower() for m in loc.region_markers]
    cities = [c.lower() for c in loc.reasonable_commute_cities]
    if not markers and not cities:
        return True, f"region unconfigured, accepted: {location!r}"
    if markers and not any(m in low for m in markers):
        region = loc.on_site_required_region or "configured region"
        return False, f"outside {region}: {location!r}"
    if any(c in low for c in cities):
        return True, f"reasonable commute: {location!r}"
    # In the configured region but not a listed commute city: keep, flagged.
    return True, f"commute unclear: {location!r}"


# ---------------------------------------------------------------------------
# Company / title filters
# ---------------------------------------------------------------------------
def is_staffing_agency(company: str, cfg: Config) -> bool:
    """True when the company is on the staffing-agency blacklist."""
    if not cfg.filters.exclude_staffing_agencies:
        return False
    name = company.lower()
    return any(bad.lower() in name for bad in cfg.filters.staffing_agency_blacklist)


def is_presales(title: str, cfg: Config) -> bool:
    """True for pre-sales titles (Solutions Engineer / Architect, Sales Engineer)."""
    if not cfg.filters.exclude_presales:
        return False
    low = title.lower()
    return any(t in low for t in cfg.filters.presales_titles)


def hard_filters(title: str, description: str, cfg: Config) -> list[str]:
    """Return a list of hard-filter violations (empty = pass)."""
    text = f"{title} {description}"
    violations: list[str] = []
    if _CITIZEN_CLEARANCE.search(text):
        violations.append("requires U.S. citizenship or security clearance")
    if _HEAVY_SWE.search(text) and "data analyst" not in text.lower():
        violations.append("core role is heavy SWE/MLE production engineering")
    if is_presales(title, cfg):
        violations.append("pre-sales title")
    strategy_re = re.compile(
        r"\b(management consultant|strategy consultant|pre[\s-]?sales consultant)\b",
        re.IGNORECASE,
    )
    if cfg.filters.exclude_strategy_consulting and strategy_re.search(text):
        violations.append("strategy/management/pre-sales consulting")
    return violations


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """Normalize a URL for dedupe: lowercase host, strip query/fragment/trailing slash."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((parsed.scheme.lower(), host, path, "", "", ""))
    except Exception:
        return url.strip().lower()


def posting_key(posting: JobPosting) -> tuple[str, str, str]:
    """Dedupe key: (normalized url, company lower, title lower)."""
    return (
        normalize_url(posting.url),
        posting.company.strip().lower(),
        posting.title.strip().lower(),
    )


def dedupe(
    postings: list[JobPosting], seen_keys: set[tuple[str, str, str]] | None = None
) -> tuple[list[JobPosting], list[JobPosting]]:
    """Split postings into (new, duplicates) against ``seen_keys``.

    ``seen_keys`` is mutated in place with the keys of the new postings.
    """
    if seen_keys is None:
        seen_keys = set()
    new, dupes = [], []
    for p in postings:
        key = posting_key(p)
        if key in seen_keys:
            dupes.append(p)
        else:
            seen_keys.add(key)
            new.append(p)
    return new, dupes


# ---------------------------------------------------------------------------
# Full evaluation
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    posting: JobPosting
    accepted: bool
    track: str | None
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def evaluate_posting(
    posting: JobPosting, cfg: Config, now: datetime | None = None
) -> Evaluation:
    """Run every scout filter on one posting; never raises on bad input."""
    reasons: list[str] = []
    flags: list[str] = []

    # Staffing agency / hard filters.
    if is_staffing_agency(posting.company, cfg):
        return Evaluation(posting, False, None,
                          reasons=["staffing agency"], flags=["staffing_agency"])
    violations = hard_filters(posting.title, "", cfg)
    if violations:
        return Evaluation(posting, False, None,
                          reasons=violations, flags=["hard_filter"])

    # Freshness.
    if not is_fresh(posting.posted_at, posting.source, cfg, now=now):
        return Evaluation(posting, False, None,
                          reasons=["outside freshness window or bad date"],
                          flags=["stale"])

    # Track classification.
    track = classify_track(posting.title, "", cfg)
    if track is None:
        return Evaluation(posting, False, None,
                          reasons=["no track keyword match"], flags=["off_track"])

    # Level.
    level = judge_level(posting.title, "", cfg, track=track)
    if not level.accepted:
        return Evaluation(posting, False, track,
                          reasons=[f"level: {level.reason}"], flags=["level"])
    flags.extend(level.flags)

    # Location.
    ok, loc_reason = location_ok(posting.location, posting.remote, cfg)
    if not ok:
        return Evaluation(posting, False, track,
                          reasons=[f"location: {loc_reason}"], flags=["location"])
    if "commute unclear" in loc_reason:
        flags.append("commute_unclear")
    if "region unconfigured" in loc_reason:
        flags.append("region_unconfigured")

    posting.track = track
    posting.flags = flags
    return Evaluation(posting, True, track,
                      reasons=[f"track={track}", level.reason, loc_reason],
                      flags=flags)
