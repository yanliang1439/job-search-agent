"""Submitter: Hermes-style human-in-the-loop application filling.

Design philosophy (mirroring the Hermes approach): the agent does all the
mechanical form-filling work, but the human always owns

1. the final submit click (unless an explicit per-job instruction says
   otherwise AND no legal item is pending), and
2. every legal checkbox — privacy consent, arbitration agreements,
   background-check / drug-test consent, non-competes, attestations,
   e-signatures. These can NEVER be auto-submitted; each needs explicit
   per-item consent and routes the application to AWAITING_REVIEW.

Field sources, in priority order (from the 2026-10-06 rule):

- ``user_config``: facts already stored in ``user.yaml`` / environment —
  address, city, ZIP, phone, email, etc. Never ask the user for these again.
- ``simplify``: the user's Simplify profile (already filled 2026-10-03).
- ``needs_user``: only for information found in NEITHER source.

Captcha policy is configurable: ``agent_solves`` (default, user-authorized
2026-10-07) | ``ask`` | ``user_handles``.

``FormFillerAdapter`` is the browser abstraction. ``DryRunFiller`` simulates
a fill for demos/tests. ``PlaywrightFiller`` is a stub: real browser
automation requires the user's credentials, which are NEVER stored in this
repository — pass them at runtime through a secure channel instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from jobagent.config import Config
from jobagent.models import Application, ApplicationStatus, InvalidTransitionError


class FieldSource(str, Enum):
    USER_CONFIG = "user_config"
    SIMPLIFY = "simplify"
    NEEDS_USER = "needs_user"


class CaptchaPolicy(str, Enum):
    AGENT_SOLVES = "agent_solves"
    ASK = "ask"
    USER_HANDLES = "user_handles"


@dataclass
class FormField:
    """One form field with its provenance."""

    name: str
    source: FieldSource
    value: str | None = None  # resolved value, if any
    required: bool = True
    is_legal: bool = False  # legal checkboxes / attestations
    legal_key: str = ""  # one of cfg.legal_items when is_legal

    @property
    def resolved(self) -> bool:
        if self.is_legal:
            # Legal items are only "resolved" by explicit per-item consent,
            # which is tracked separately in ReviewGate.
            return False
        return self.value is not None and self.value != ""


@dataclass
class FormFillPlan:
    """Plan for filling one application form."""

    application_id: int | None
    fields: list[FormField] = field(default_factory=list)

    def unresolved_required(self) -> list[FormField]:
        """Required non-legal fields still missing a value."""
        return [f for f in self.fields if f.required and not f.is_legal and not f.resolved]

    def pending_legal(self, legal_items: tuple[str, ...]) -> list[FormField]:
        """Legal items that still need explicit per-item consent."""
        return [
            f
            for f in self.fields
            if f.is_legal and (not f.legal_key or f.legal_key in legal_items)
        ]

    def auto_fillable(self) -> list[FormField]:
        """Fields the agent may fill without asking."""
        return [
            f
            for f in self.fields
            if f.source in (FieldSource.USER_CONFIG, FieldSource.SIMPLIFY)
            and not f.is_legal
            and f.resolved
        ]


@dataclass
class ReviewGate:
    """Decides whether the agent may submit without another human review."""

    cfg: Config
    legal_consents: dict[str, bool] = field(default_factory=dict)
    captcha_policy: CaptchaPolicy = CaptchaPolicy.AGENT_SOLVES

    def can_auto_submit(self, plan: FormFillPlan) -> tuple[bool, str]:
        """Return (allowed, reason).

        Auto-submit is allowed only when:

        - every required field is resolved from an approved source
          (user_config / simplify), and
        - there are no pending legal items (privacy consent, arbitration,
          background check, drug test, non-compete, attestation,
          e-signature) — each needs explicit per-item consent.

        Captcha handling follows the configured policy and never blocks the
        gate by itself.
        """
        unresolved = plan.unresolved_required()
        if unresolved:
            names = ", ".join(f.name for f in unresolved)
            return False, f"unresolved required fields: {names}"

        pending = plan.pending_legal(self.cfg.legal_items)
        still_pending = [
            f for f in pending if not self.legal_consents.get(f.legal_key, False)
        ]
        if still_pending:
            names = ", ".join(f.legal_key or f.name for f in still_pending)
            return False, f"pending legal items need explicit consent: {names}"

        return True, "all required fields resolved; no pending legal items"


# ---------------------------------------------------------------------------
# Filler adapters
# ---------------------------------------------------------------------------
class FillResult(str, Enum):
    FILLED = "FILLED"
    STOPPED_BEFORE_SUBMIT = "STOPPED_BEFORE_SUBMIT"
    SUBMITTED = "SUBMITTED"
    BLOCKED = "BLOCKED"


@dataclass
class FillReport:
    result: FillResult
    filled_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class FormFillerAdapter(ABC):
    """Browser abstraction for filling one application form."""

    @abstractmethod
    def fill(self, plan: FormFillPlan, application: Application) -> FillReport:
        """Fill the form per the plan; never click submit."""


class DryRunFiller(FormFillerAdapter):
    """Simulated filler for demos and tests. Touches no browser."""

    def fill(self, plan: FormFillPlan, application: Application) -> FillReport:
        report = FillReport(result=FillResult.FILLED)
        for f in plan.fields:
            if f.is_legal:
                report.skipped_fields.append(f.name)
                report.notes.append(
                    f"legal item left for the user: {f.legal_key or f.name}"
                )
            elif f.resolved:
                report.filled_fields.append(f.name)
            else:
                report.skipped_fields.append(f.name)
                report.notes.append(f"needs user input: {f.name}")
        return report


class PlaywrightFiller(FormFillerAdapter):
    """Stub for a real Playwright-backed filler.

    NOT IMPLEMENTED in this repository on purpose: driving a real browser
    needs the user's ATS credentials, which must NEVER be committed here.
    To implement, subclass and inject credentials at runtime through a secure
    channel (e.g. environment variables on the operator's machine, a vault,
    or an interactive login the user performs themselves).
    """

    def __init__(self, **kwargs: object) -> None:
        raise NotImplementedError(
            "PlaywrightFiller is a stub. Implement fill() in a subclass and "
            "pass credentials at runtime; never store them in this repository."
        )

    def fill(self, plan: FormFillPlan, application: Application) -> FillReport:  # noqa: D102
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Orchestration: fill then gate
# ---------------------------------------------------------------------------
def run_submission_flow(
    application: Application,
    plan: FormFillPlan,
    filler: FormFillerAdapter,
    gate: ReviewGate,
) -> tuple[FillReport, bool, str]:
    """Fill the form, then decide whether auto-submit is allowed.

    Returns (fill_report, may_auto_submit, gate_reason). The caller owns the
    actual submit click; this function never submits.

    Status flow:
    QUEUED -> FILLING -> (gate passes) READY_TO_SUBMIT
                     -> (gate fails)  AWAITING_REVIEW
    """
    if application.status is ApplicationStatus.QUEUED:
        application.transition(ApplicationStatus.FILLING)

    report = filler.fill(plan, application)
    allowed, reason = gate.can_auto_submit(plan)

    try:
        if allowed:
            application.transition(ApplicationStatus.READY_TO_SUBMIT)
        else:
            application.transition(ApplicationStatus.AWAITING_REVIEW)
    except InvalidTransitionError:
        # Application was already past the fill stage; leave it alone.
        pass

    return report, allowed, reason
