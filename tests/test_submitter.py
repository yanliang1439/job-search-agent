"""Tests for the Hermes-style human-in-the-loop submitter."""

import pytest

from jobagent import submitter
from jobagent.config import Config
from jobagent.models import Application, ApplicationStatus, InvalidTransitionError

FS = submitter.FieldSource


def make_plan(include_legal: bool = True) -> submitter.FormFillPlan:
    fields = [
        submitter.FormField("full_name", FS.USER_CONFIG, value="Jane Doe"),
        submitter.FormField("email", FS.USER_CONFIG, value="jane@example.com"),
        submitter.FormField("cover_letter", FS.NEEDS_USER, value="Dear hiring..."),
    ]
    if include_legal:
        fields.append(
            submitter.FormField(
                "privacy_consent", FS.NEEDS_USER, is_legal=True,
                legal_key="privacy_consent",
            )
        )
    return submitter.FormFillPlan(application_id=None, fields=fields)


def test_unresolved_required_blocks_gate(cfg: Config):
    plan = make_plan(include_legal=False)
    plan.fields.append(submitter.FormField("phone", FS.NEEDS_USER))  # no value
    gate = submitter.ReviewGate(cfg=cfg)
    allowed, reason = gate.can_auto_submit(plan)
    assert not allowed
    assert "phone" in reason


def test_pending_legal_blocks_gate(cfg: Config):
    plan = make_plan(include_legal=True)
    gate = submitter.ReviewGate(cfg=cfg)
    allowed, reason = gate.can_auto_submit(plan)
    assert not allowed
    assert "privacy_consent" in reason


def test_explicit_legal_consent_allows_gate(cfg: Config):
    plan = make_plan(include_legal=True)
    gate = submitter.ReviewGate(
        cfg=cfg, legal_consents={"privacy_consent": True}
    )
    allowed, _ = gate.can_auto_submit(plan)
    assert allowed


def test_legal_never_auto_resolved():
    f = submitter.FormField(
        "privacy_consent", FS.USER_CONFIG, value="yes",
        is_legal=True, legal_key="privacy_consent",
    )
    assert not f.resolved  # legal items need explicit per-item consent


def test_flow_routes_to_awaiting_review_when_blocked(cfg: Config):
    app = Application(company="Acme", title="Data Analyst")
    plan = make_plan(include_legal=True)
    gate = submitter.ReviewGate(cfg=cfg)
    report, allowed, _ = submitter.run_submission_flow(
        app, plan, submitter.DryRunFiller(), gate
    )
    assert not allowed
    assert app.status is ApplicationStatus.AWAITING_REVIEW
    assert "privacy_consent" in report.skipped_fields


def test_flow_routes_to_ready_when_clear(cfg: Config):
    app = Application(company="Acme", title="Data Analyst")
    plan = make_plan(include_legal=False)
    gate = submitter.ReviewGate(cfg=cfg)
    _, allowed, _ = submitter.run_submission_flow(
        app, plan, submitter.DryRunFiller(), gate
    )
    assert allowed
    assert app.status is ApplicationStatus.READY_TO_SUBMIT
    assert app.can_auto_submit()


def test_flow_never_submits_by_itself(cfg: Config):
    app = Application(company="Acme", title="Data Analyst")
    plan = make_plan(include_legal=False)
    gate = submitter.ReviewGate(cfg=cfg)
    submitter.run_submission_flow(app, plan, submitter.DryRunFiller(), gate)
    assert app.status is not ApplicationStatus.SUBMITTED


def test_illegal_transition_rejected():
    app = Application(company="Acme", title="Data Analyst",
                      status=ApplicationStatus.SUBMITTED)
    with pytest.raises(InvalidTransitionError):
        app.transition(ApplicationStatus.FILLING)


def test_failed_can_be_requeued():
    app = Application(company="Acme", title="Data Analyst",
                      status=ApplicationStatus.FAILED)
    app.transition(ApplicationStatus.QUEUED)
    assert app.status is ApplicationStatus.QUEUED


def test_playwright_stub_raises():
    with pytest.raises(NotImplementedError):
        submitter.PlaywrightFiller()


def test_captcha_policy_default(cfg: Config):
    assert cfg.captcha_policy == "agent_solves"
    gate = submitter.ReviewGate(cfg=cfg)
    assert gate.captcha_policy is submitter.CaptchaPolicy.AGENT_SOLVES
