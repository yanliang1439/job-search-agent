"""Shared fixtures for the jobagent test suite.

The ``cfg`` fixture builds an explicit, self-contained Config so tests never
depend on files on disk (personal or example configs).
"""

import pytest

from jobagent.config import (
    ATSRules,
    Config,
    DigestRules,
    FilterRules,
    LevelRules,
    LocationRules,
)


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config(
        job_board_freshness_hours=24,
        university_freshness_days=14,
        tracks={
            "primary": [
                "data analyst",
                "product analyst",
                "bi analyst",
                "business data analyst",
                "product data scientist",
                "decision scientist",
                "monetization analyst",
                "growth analyst",
                "lifecycle marketing",
                "revenue analyst",
                "advertising analytics",
            ],
            "secondary": ["ai product analyst", "applied ai analyst"],
            "extended": [
                "analytics consultant",
                "data consultant",
                "technical account manager",
            ],
            "selective": ["analytics engineer"],
        },
        track_order=("primary", "secondary", "extended", "selective"),
        levels=LevelRules(strong_match_ratio=0.5),
        location=LocationRules(
            remote_ok=True,
            on_site_required_region="Bay Area, CA",
            home_base="Fremont, CA",
            region_markers=(
                "bay area",
                "san francisco",
                "san jose",
                "california",
            ),
            reasonable_commute_cities=("San Jose", "Fremont"),
        ),
        filters=FilterRules(
            staffing_agency_blacklist=("Aquent",),
            exclude_staffing_agencies=True,
            presales_titles=(
                "solutions engineer",
                "solutions architect",
                "sales engineer",
            ),
            exclude_presales=True,
        ),
        ats=ATSRules(),
        digest=DigestRules(),
        captcha_policy="agent_solves",
    )
