"""Tests for the SQLite application tracker."""

import pytest

from jobagent import tracker
from jobagent.models import Application, ApplicationStatus, InvalidTransitionError


@pytest.fixture()
def t():
    with tracker.Tracker(":memory:") as tr:
        yield tr


def sample() -> Application:
    return Application(
        company="Acme",
        title="Data Analyst",
        url="https://example.com/j/1",
        track="primary",
        ats_score=82,
        notes="tailored resume ready",
    )


def test_add_and_get(t: tracker.Tracker):
    app_id = t.add(sample())
    got = t.get(app_id)
    assert got is not None
    assert got.company == "Acme"
    assert got.status is ApplicationStatus.QUEUED
    assert got.ats_score == 82


def test_get_missing_returns_none(t: tracker.Tracker):
    assert t.get(999) is None


def test_update_persists_notes(t: tracker.Tracker):
    app_id = t.add(sample())
    app = t.get(app_id)
    app.notes = "submitted"
    app.confirmation_no = "CONF-123"
    t.update(app)
    assert t.get(app_id).confirmation_no == "CONF-123"


def test_set_status_valid_transition(t: tracker.Tracker):
    app_id = t.add(sample())
    app = t.set_status(app_id, ApplicationStatus.FILLING)
    assert app.status is ApplicationStatus.FILLING
    assert t.get(app_id).status is ApplicationStatus.FILLING


def test_set_status_invalid_transition(t: tracker.Tracker):
    app_id = t.add(sample())
    with pytest.raises(InvalidTransitionError):
        t.set_status(app_id, ApplicationStatus.SUBMITTED)  # QUEUED -> SUBMITTED illegal


def test_submit_stamps_applied_at(t: tracker.Tracker):
    app_id = t.add(sample())
    t.set_status(app_id, ApplicationStatus.FILLING)
    t.set_status(app_id, ApplicationStatus.READY_TO_SUBMIT)
    app = t.set_status(app_id, ApplicationStatus.SUBMITTED)
    assert app.applied_at != ""


def test_list_and_filter(t: tracker.Tracker):
    t.add(sample())
    second_sample = sample()
    second_sample.url = "https://example.com/j/2"
    t.add(second_sample)
    second = t.list()[1]
    t.set_status(second.id, ApplicationStatus.FILLING)
    assert len(t.list()) == 2
    assert len(t.list(ApplicationStatus.QUEUED)) == 1
    assert len(t.list(ApplicationStatus.FILLING)) == 1


def test_delete(t: tracker.Tracker):
    app_id = t.add(sample())
    assert t.delete(app_id)
    assert t.get(app_id) is None
    assert not t.delete(app_id)


def test_count_by_status(t: tracker.Tracker):
    t.add(sample())
    counts = t.count_by_status()
    assert counts.get("QUEUED") == 1


def test_get_by_url(t: tracker.Tracker):
    t.add(sample())
    got = t.get_by_url("https://example.com/j/1")
    assert got is not None and got.company == "Acme"
