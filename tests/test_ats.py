"""Tests for deterministic ATS scoring and band assignment."""

from jobagent import ats
from jobagent.config import Config

JD = """
Data Analyst needed. Required: SQL, Python, Tableau, A/B testing.
Preferred: dbt, statistics. You will build dashboards and run experiments.
"""

BANK = ["SQL", "Python", "Tableau", "A/B testing", "dbt", "statistics"]


def test_perfect_match_priority_band(cfg: Config):
    r = ats.score_jd(
        JD,
        required=["SQL", "Python", "Tableau", "A/B testing"],
        preferred=["dbt", "statistics"],
        candidate_skills=BANK,
        cfg=cfg,
    )
    assert r.score >= 85
    assert r.band == "priority"
    assert set(r.matched) == set(
        ["SQL", "Python", "Tableau", "A/B testing", "dbt", "statistics"]
    )
    assert r.missed == []


def test_missing_hard_requirements_skip_band(cfg: Config):
    r = ats.score_jd(
        JD,
        required=["SQL", "Python", "Tableau", "Looker"],
        candidate_skills=["SQL"],
        cfg=cfg,
    )
    assert r.band == "skip"
    assert r.score < 60
    assert "Python" in r.missed and "Tableau" in r.missed


def test_low_priority_band(cfg: Config):
    # earned 9/12 = 75, minus 6 penalty for the missed required Excel -> 69
    r = ats.score_jd(
        "SQL Python Tableau role.",
        required=["SQL", "Python", "Tableau", "Excel"],
        candidate_skills=["SQL", "Python", "Tableau"],
        cfg=cfg,
    )
    assert r.band == "low_priority"
    assert r.score == 69


def test_required_skill_not_in_bank_counts_as_missed(cfg: Config):
    r = ats.score_jd(
        JD,
        required=["SQL", "Rust"],
        candidate_skills=["SQL"],
        cfg=cfg,
    )
    assert "Rust" in r.missed


def test_deterministic(cfg: Config):
    kwargs = dict(
        required=["SQL", "Python"],
        preferred=["dbt"],
        candidate_skills=["SQL", "Python"],
        cfg=cfg,
    )
    assert ats.score_jd(JD, **kwargs).score == ats.score_jd(JD, **kwargs).score


def test_empty_requirements_scores_zero(cfg: Config):
    r = ats.score_jd(JD, required=[], cfg=cfg)
    assert r.score == 0
    assert r.band == "skip"
