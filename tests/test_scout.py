"""Tests for scout filters: freshness, tracks, levels, location, dedupe."""

from datetime import datetime, timedelta, timezone

import pytest

from jobagent import scout
from jobagent.config import Config
from jobagent.models import JobPosting

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def posting(**kw) -> JobPosting:
    base = dict(
        company="Acme",
        title="Data Analyst",
        url="https://example.com/j/1",
        location="San Jose, CA",
        posted_at=iso(NOW - timedelta(hours=2)),
        source="job_board",
        verified=True,
    )
    base.update(kw)
    return JobPosting(**base)


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------
def test_job_board_fresh_within_24h(cfg: Config):
    assert scout.is_fresh(iso(NOW - timedelta(hours=23)), "job_board", cfg, NOW)


def test_job_board_stale_after_24h(cfg: Config):
    assert not scout.is_fresh(iso(NOW - timedelta(hours=25)), "job_board", cfg, NOW)


def test_university_window_14_days(cfg: Config):
    assert scout.is_fresh(iso(NOW - timedelta(days=13)), "university", cfg, NOW)
    assert not scout.is_fresh(iso(NOW - timedelta(days=15)), "university", cfg, NOW)


def test_bad_date_fails_closed(cfg: Config):
    assert not scout.is_fresh("not-a-date", "job_board", cfg, NOW)
    assert not scout.is_fresh("", "job_board", cfg, NOW)


def test_future_date_not_fresh(cfg: Config):
    assert not scout.is_fresh(iso(NOW + timedelta(hours=1)), "job_board", cfg, NOW)


# ---------------------------------------------------------------------------
# track classification
# ---------------------------------------------------------------------------
def test_classify_primary(cfg: Config):
    assert scout.classify_track("Data Analyst", "", cfg) == "primary"
    assert scout.classify_track("Product Data Scientist", "", cfg) == "primary"


def test_classify_extended(cfg: Config):
    assert scout.classify_track("Analytics Consultant", "", cfg) == "extended"


def test_classify_none(cfg: Config):
    assert scout.classify_track("Line Cook", "", cfg) is None


def test_primary_wins_over_extended(cfg: Config):
    # contains keywords from both tracks; primary has priority
    assert (
        scout.classify_track("Data Analyst, Product Operations", "", cfg)
        == "primary"
    )


# ---------------------------------------------------------------------------
# level judgement
# ---------------------------------------------------------------------------
def test_senior_rejected(cfg: Config):
    d = scout.judge_level("Senior Data Analyst", "5+ years experience", cfg)
    assert not d.accepted


def test_staff_principal_rejected(cfg: Config):
    assert not scout.judge_level("Staff Data Analyst", "", cfg).accepted
    assert not scout.judge_level("Principal Analyst", "", cfg).accepted


def test_junior_family_accepted(cfg: Config):
    assert scout.judge_level("Junior Data Analyst", "", cfg).accepted
    assert scout.judge_level("Associate Data Analyst", "", cfg).accepted
    assert scout.judge_level("Data Analyst II", "", cfg).accepted


def test_people_management_rejected(cfg: Config):
    d = scout.judge_level(
        "Data Analyst Manager", "You will manage a team of 5 analysts.", cfg
    )
    assert not d.accepted


STRONG_DESC = (
    "Data Analyst role. Work with product analyst peers on BI analyst tasks: "
    "business data analyst dashboards, decision scientist reviews, "
    "monetization analyst metrics, growth analyst experiments, "
    "lifecycle marketing analysis, revenue analyst reporting, "
    "advertising analytics deep dives."
)


def test_3_to_5_years_strong_match_accepted(cfg: Config):
    d = scout.judge_level(
        "Data Analyst", f"Requires 3-5 years of experience. {STRONG_DESC}",
        cfg, track="primary",
    )
    assert d.accepted
    assert "strong_match" in d.flags


def test_3_to_5_years_weak_match_rejected(cfg: Config):
    d = scout.judge_level(
        "Data Analyst", "Requires 3-5 years of experience.", cfg, track="primary"
    )
    assert not d.accepted


def test_mid_ic_without_strong_match_rejected(cfg: Config):
    d = scout.judge_level("Mid-level Data Analyst", "SQL and dashboards.", cfg,
                          track="primary")
    assert not d.accepted


def test_mid_ic_strong_match_accepted(cfg: Config):
    d = scout.judge_level("Mid-level Data Analyst", STRONG_DESC, cfg, track="primary")
    assert d.accepted
    assert "strong_match" in d.flags


def test_new_grad_only_accepted_with_caution(cfg: Config):
    d = scout.judge_level(
        "Junior Data Analyst", "New grads only. 0-2 years of experience.", cfg
    )
    assert d.accepted
    assert "caution_overqualified" in d.flags


# ---------------------------------------------------------------------------
# location
# ---------------------------------------------------------------------------
def test_remote_ok(cfg: Config):
    ok, _ = scout.location_ok("Remote", True, cfg)
    assert ok


def test_bay_area_ok(cfg: Config):
    ok, _ = scout.location_ok("San Jose, CA", False, cfg)
    assert ok


def test_outside_bay_area_rejected(cfg: Config):
    ok, _ = scout.location_ok("New York, NY", False, cfg)
    assert not ok


# ---------------------------------------------------------------------------
# company / hard filters
# ---------------------------------------------------------------------------
def test_staffing_agency_detected(cfg: Config):
    assert scout.is_staffing_agency("Aquent LLC", cfg)
    assert not scout.is_staffing_agency("Google", cfg)


def test_presales_detected(cfg: Config):
    assert scout.is_presales("Solutions Engineer", cfg)
    assert scout.is_presales("Sales Engineer", cfg)
    assert not scout.is_presales("Data Analyst", cfg)


def test_hard_filter_citizenship(cfg: Config):
    v = scout.hard_filters("Data Analyst", "Must be a U.S. citizen.", cfg)
    assert any("citizenship" in x for x in v)


def test_hard_filter_heavy_swe(cfg: Config):
    v = scout.hard_filters(
        "Software Development Engineer", "Build microservices on Kubernetes.", cfg
    )
    assert v


def test_hard_filter_presales(cfg: Config):
    v = scout.hard_filters("Solutions Architect", "Pre-sales demos.", cfg)
    assert any("pre-sales" in x for x in v)


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------
def test_dedupe_same_posting(cfg: Config):
    seen: set = set()
    p1 = posting()
    p2 = posting(url="https://example.com/j/1?utm_source=linkedin#frag")
    new, dupes = scout.dedupe([p1, p2], seen)
    assert len(new) == 1 and len(dupes) == 1


def test_dedupe_distinct_postings(cfg: Config):
    p1 = posting(url="https://example.com/j/1")
    p2 = posting(url="https://example.com/j/2")
    new, dupes = scout.dedupe([p1, p2], set())
    assert len(new) == 2 and not dupes


def test_evaluate_posting_end_to_end(cfg: Config):
    ev = scout.evaluate_posting(posting(), cfg, now=NOW)
    assert ev.accepted
    assert ev.track == "primary"


def test_evaluate_posting_rejects_staffing(cfg: Config):
    ev = scout.evaluate_posting(posting(company="Aquent LLC"), cfg, now=NOW)
    assert not ev.accepted


def test_evaluate_posting_rejects_stale(cfg: Config):
    ev = scout.evaluate_posting(
        posting(posted_at=iso(NOW - timedelta(days=3))), cfg, now=NOW
    )
    assert not ev.accepted
