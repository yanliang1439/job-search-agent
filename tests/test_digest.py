"""Tests for digest building: verified zones, caps, track minimums, priority."""

from jobagent import digest
from jobagent.config import Config
from jobagent.models import JobPosting


def make(i: int, track: str, verified: bool = True) -> JobPosting:
    return JobPosting(
        company=f"Company{i:02d}",
        title=f"{track.title()} Analyst {i}",
        url=f"https://example.com/j/{track}/{i}",
        location="San Jose, CA",
        track=track,
        verified=verified,
        verification_note="" if verified else "JD page did not load",
        match_reason="keyword match",
    )


def test_unverified_goes_to_pending_zone_not_counted(cfg: Config):
    posts = [make(1, "primary"), make(2, "primary", verified=False)]
    md = digest.build_digest(posts, cfg)
    assert "Pending verification" in md
    assert "Company02" in md.split("Pending verification")[1]
    assert "Company02" not in md.split("Pending verification")[0]


def test_cap_20_with_overflow(cfg: Config):
    posts = [make(i, "primary") for i in range(30)]
    md = digest.build_digest(posts, cfg)
    assert "exceed the 20-entry cap" in md
    # 20 chosen -> "Primary (20)" header
    assert "Primary (20)" in md


def test_per_track_minimum(cfg: Config):
    posts = [make(i, "primary") for i in range(10)]
    posts += [make(100 + i, "secondary") for i in range(2)]
    md = digest.build_digest(posts, cfg)
    # secondary has only 2 -> both shown (fewer than minimum: show what there is)
    assert "Secondary (2)" in md


def test_priority_fill_order(cfg: Config):
    # 3 primary, 3 secondary, 10 extended: all 16 fit under the cap of 20
    posts = [make(i, "primary") for i in range(3)]
    posts += [make(100 + i, "secondary") for i in range(3)]
    posts += [make(200 + i, "extended") for i in range(10)]
    md = digest.build_digest(posts, cfg)
    assert "Primary (3)" in md
    assert "Secondary (3)" in md
    assert "Extended (10)" in md


def test_remaining_slots_follow_priority(cfg: Config):
    # 25 primary + 10 extended: minimums take 3+3=6, remaining 14 go primary first
    posts = [make(i, "primary") for i in range(25)]
    posts += [make(200 + i, "extended") for i in range(10)]
    md = digest.build_digest(posts, cfg)
    assert "Primary (17)" in md
    assert "Extended (3)" in md


def test_empty_digest(cfg: Config):
    md = digest.build_digest([], cfg)
    assert "No new postings today." in md


def test_flags_rendered(cfg: Config):
    p = make(1, "primary")
    p.flags = ["caution_overqualified"]
    md = digest.build_digest([p], cfg)
    assert "caution_overqualified" in md
