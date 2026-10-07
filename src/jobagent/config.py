"""Configuration loading.

Rules:

- ``preferences.yaml`` holds search/filter/digest rules and defaults. Copy
  ``config/preferences.example.yaml`` to ``config/preferences.yaml``.
- Personal data is NEVER read from the repo. It comes only from the
  gitignored ``config/user.yaml`` or from ``JOBAGENT_<FIELD>`` environment
  variables. If neither exists, placeholders are used.
- No third-party dependencies: the tiny YAML subset used here (nested maps,
  lists, scalars, comments) is parsed with a built-in minimal parser.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_PREFIX = "JOBAGENT_"

# Environment variable names that may carry personal data.
PERSONAL_ENV_FIELDS = (
    "FULL_NAME",
    "EMAIL",
    "RESUME_EMAIL",
    "PHONE",
    "LINKEDIN",
    "GITHUB",
    "CITY",
    "STATE",
    "ZIP",
    "STREET_ADDRESS",
    "HOME_BASE",
)

DEFAULT_TRACK_ORDER = ["primary", "secondary", "extended", "selective"]


# ---------------------------------------------------------------------------
# Minimal YAML subset parser (stdlib only)
# ---------------------------------------------------------------------------
def _parse_scalar(value: str) -> Any:
    value = value.strip()
    # Flow-style list: [a, b, c]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_yaml_subset(text: str) -> dict:
    """Parse a simple nested-mapping/list YAML subset.

    Supports: 2-space indented nested maps, ``- item`` lists, ``key: value``
    pairs, ``#`` comments, and quoted scalars. Raises ValueError on tabs.
    """
    lines = []
    for raw in text.splitlines():
        if "\t" in raw:
            raise ValueError("YAML subset parser does not accept tab indentation")
        # Strip inline comments so `key:  # comment` still opens a nested block.
        stripped = raw.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        lines.append(stripped)

    root: dict = {}
    # stack entries: (indent, container, parent, key_in_parent)
    stack: list[tuple[int, Any, Any, Any]] = [(-1, root, None, None)]

    for raw in lines:
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        _, container, _, _ = stack[-1]

        if content.startswith("- "):
            item = _parse_scalar(content[2:])
            if not isinstance(container, list):
                raise ValueError(f"List item under non-list context: {raw!r}")
            container.append(item)
            continue

        if ":" not in content:
            raise ValueError(f"Cannot parse line: {raw!r}")
        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            if isinstance(container, dict):
                container[key] = _parse_scalar(value)
            else:
                raise ValueError(f"Mapping entry under non-map context: {raw!r}")
        else:
            # Nested block: decide list vs map by looking ahead.
            idx = lines.index(raw)
            child_is_list = False
            for nxt in lines[idx + 1 :]:
                nindent = len(nxt) - len(nxt.lstrip(" "))
                ncontent = nxt.strip()
                if nindent > indent:
                    child_is_list = ncontent.startswith("- ")
                    break
                if nindent <= indent:
                    break
            child: Any = [] if child_is_list else {}
            if isinstance(container, dict):
                container[key] = child
            else:
                raise ValueError(f"Nested block under non-map context: {raw!r}")
            stack.append((indent, child, container, key))

    return root


def load_yaml_file(path: str | Path) -> dict:
    """Load a YAML-subset file; returns {} if the file does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    return _parse_yaml_subset(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Typed configuration
# ---------------------------------------------------------------------------
@dataclass
class LevelRules:
    accepted: tuple = ("entry", "junior", "associate", "i", "ii")
    outright_max_years: float = 3.0
    strong_match_max_years: float = 5.0
    mid_ic_strong_match_only: bool = True
    excluded: tuple = ("senior", "staff", "principal")
    exclude_people_management: bool = True
    accept_new_grad_only_with_caution_flag: bool = True
    strong_match_ratio: float = 0.5  # min fraction of track keywords for a strong match


@dataclass
class LocationRules:
    remote_ok: bool = True
    on_site_required_region: str = ""
    region_markers: tuple = ()  # substrings identifying the region, e.g. ("bay area",)
    home_base: str = "<HOME_BASE>"
    reasonable_commute_cities: tuple = ()


@dataclass
class FilterRules:
    staffing_agency_blacklist: tuple = ()
    exclude_staffing_agencies: bool = True
    presales_titles: tuple = ()
    exclude_presales: bool = True
    exclude_strategy_consulting: bool = True
    consultative_travel_flag: bool = True


@dataclass
class ATSRules:
    priority_threshold: int = 85
    recommend_threshold: int = 75
    low_priority_threshold: int = 60


@dataclass
class DigestRules:
    max_entries: int = 20
    min_per_track: int = 3
    track_order: tuple = ("primary", "secondary", "extended", "selective")
    unverified_counts_toward_cap: bool = False


@dataclass
class PersonalInfo:
    """Personal data; defaults are placeholders, NEVER real values.

    Real values come only from the gitignored ``config/user.yaml`` or from
    ``JOBAGENT_*`` environment variables.
    """

    full_name: str = "<FULL_NAME>"
    email: str = "<EMAIL>"
    resume_email: str = "<EMAIL>"
    phone: str = "<PHONE>"
    linkedin: str = "<LINKEDIN_URL>"
    github: str = "<GITHUB_URL>"
    city: str = "<CITY>"
    state: str = "<STATE>"
    zip: str = "<ZIP>"
    street_address: str = "<STREET_ADDRESS>"
    home_base: str = "<HOME_BASE>"
    graduation: str = "Expected Jun 2027"
    work_authorization: str = "Authorized to work in the U.S."
    needs_sponsorship: bool = False


@dataclass
class Config:
    job_board_freshness_hours: int = 24
    university_freshness_days: int = 14
    tracks: dict = field(default_factory=dict)  # track name -> [keywords]
    track_order: tuple = tuple(DEFAULT_TRACK_ORDER)
    levels: LevelRules = field(default_factory=LevelRules)
    location: LocationRules = field(default_factory=LocationRules)
    filters: FilterRules = field(default_factory=FilterRules)
    ats: ATSRules = field(default_factory=ATSRules)
    digest: DigestRules = field(default_factory=DigestRules)
    captcha_policy: str = "agent_solves"  # agent_solves | ask | user_handles
    legal_items: tuple = (
        "privacy_consent",
        "arbitration_agreement",
        "background_check_consent",
        "drug_test_consent",
        "non_compete",
        "attestation",
        "e_signature",
    )
    personal: PersonalInfo = field(default_factory=PersonalInfo)


def _get(d: dict, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_config(project_root: str | Path | None = None) -> Config:
    """Load preferences.yaml + keywords.yaml + user.yaml/env into a Config.

    ``project_root`` defaults to the repository root (parent of ``src/``).
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parents[2]
    root = Path(project_root)
    config_dir = root / "config"

    prefs = load_yaml_file(config_dir / "preferences.yaml")
    if not prefs:
        prefs = load_yaml_file(config_dir / "preferences.example.yaml")
    keywords = load_yaml_file(config_dir / "keywords.yaml")
    if not keywords:
        keywords = load_yaml_file(config_dir / "keywords.example.yaml")
    user = load_yaml_file(config_dir / "user.yaml")

    cfg = Config()

    # --- search windows ---
    cfg.job_board_freshness_hours = int(
        _get(prefs, "search", "job_board_freshness_hours", default=24)
    )
    cfg.university_freshness_days = int(
        _get(prefs, "search", "university_freshness_days", default=14)
    )

    # --- tracks ---
    track_keywords = _get(keywords, "tracks", default={}) or {}
    cfg.tracks = {
        name: [str(k) for k in kws] for name, kws in track_keywords.items()
    }
    track_order = _get(prefs, "tracks", "order", default=list(DEFAULT_TRACK_ORDER))
    cfg.track_order = tuple(track_order)
    min_per_track = int(_get(prefs, "tracks", "min_per_track", default=3))

    # --- levels ---
    lvl = _get(prefs, "levels", default={}) or {}
    cfg.levels = LevelRules(
        accepted=tuple(lvl.get("accepted", LevelRules.accepted)),
        outright_max_years=float(lvl.get("outright_max_years", 3.0)),
        strong_match_max_years=float(lvl.get("strong_match_max_years", 5.0)),
        mid_ic_strong_match_only=bool(
            lvl.get("mid_ic_strong_match_only", True)
        ),
        excluded=tuple(lvl.get("excluded", LevelRules.excluded)),
        exclude_people_management=bool(
            lvl.get("exclude_people_management", True)
        ),
        accept_new_grad_only_with_caution_flag=bool(
            lvl.get("accept_new_grad_only_with_caution_flag", True)
        ),
        strong_match_ratio=float(lvl.get("strong_match_ratio", 0.5)),
    )

    # --- location ---
    loc = _get(prefs, "location", default={}) or {}
    cfg.location = LocationRules(
        remote_ok=bool(loc.get("remote_ok", True)),
        on_site_required_region=str(loc.get("on_site_required_region", "")),
        region_markers=tuple(
            loc.get("region_markers", LocationRules.region_markers)
        ),
        home_base=str(loc.get("home_base", "<HOME_BASE>")),
        reasonable_commute_cities=tuple(
            loc.get("reasonable_commute_cities", LocationRules.reasonable_commute_cities)
        ),
    )

    # --- filters ---
    flt = _get(prefs, "filters", default={}) or {}
    cfg.filters = FilterRules(
        staffing_agency_blacklist=tuple(
            flt.get("staffing_agency_blacklist", FilterRules.staffing_agency_blacklist)
        ),
        exclude_staffing_agencies=bool(flt.get("exclude_staffing_agencies", True)),
        presales_titles=tuple(
            flt.get("presales_titles", FilterRules.presales_titles)
        ),
        exclude_presales=bool(flt.get("exclude_presales", True)),
        exclude_strategy_consulting=bool(
            flt.get("exclude_strategy_consulting", True)
        ),
        consultative_travel_flag=bool(flt.get("consultative_travel_flag", True)),
    )

    # --- ATS ---
    a = _get(prefs, "ats", default={}) or {}
    cfg.ats = ATSRules(
        priority_threshold=int(a.get("priority_threshold", 85)),
        recommend_threshold=int(a.get("recommend_threshold", 75)),
        low_priority_threshold=int(a.get("low_priority_threshold", 60)),
    )

    # --- digest ---
    dg = _get(prefs, "digest", default={}) or {}
    cfg.digest = DigestRules(
        max_entries=int(dg.get("max_entries", 20)),
        min_per_track=min_per_track,
        track_order=cfg.track_order,
        unverified_counts_toward_cap=bool(
            dg.get("unverified_counts_toward_cap", False)
        ),
    )

    # --- captcha ---
    cfg.captcha_policy = str(_get(prefs, "captcha", "policy", default="agent_solves"))

    # --- legal items ---
    legal = _get(prefs, "submitter", "legal_items", default=None)
    if legal:
        cfg.legal_items = tuple(str(x) for x in legal)

    # --- personal: user.yaml first, then env overrides ---
    personal_yaml = _get(user, "personal", default={}) or {}
    personal = PersonalInfo()
    for f in PERSONAL_ENV_FIELDS:
        key = f.lower()
        env_val = os.environ.get(ENV_PREFIX + f)
        if env_val is not None:
            setattr(personal, key, env_val)
        elif key in personal_yaml:
            setattr(personal, key, str(personal_yaml[key]))
    cfg.personal = personal

    return cfg


def resolve_project_root() -> Path:
    """Return the repository root (two levels above this file)."""
    return Path(__file__).resolve().parents[2]
