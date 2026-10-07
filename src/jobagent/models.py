"""Data models for the job-search pipeline.

JobPosting flows through the scout (filter/dedupe) into the digest.
Application flows through the submitter's state machine:

    QUEUED -> FILLING -> AWAITING_REVIEW -> READY_TO_SUBMIT -> SUBMITTED
                                                          |-> FAILED
                                                          |-> BLOCKED

QUEUED can also go straight to BLOCKED (e.g. blocked at account creation).
FAILED and BLOCKED are terminal; a FAILED application may be re-queued by the
caller creating a fresh transition back through QUEUED.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ApplicationStatus(str, Enum):
    QUEUED = "QUEUED"
    FILLING = "FILLING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


# Allowed transitions between statuses.
_ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.QUEUED: frozenset(
        {ApplicationStatus.FILLING, ApplicationStatus.BLOCKED}
    ),
    ApplicationStatus.FILLING: frozenset(
        {
            ApplicationStatus.AWAITING_REVIEW,
            ApplicationStatus.READY_TO_SUBMIT,
            ApplicationStatus.FAILED,
            ApplicationStatus.BLOCKED,
        }
    ),
    ApplicationStatus.AWAITING_REVIEW: frozenset(
        {
            ApplicationStatus.FILLING,
            ApplicationStatus.READY_TO_SUBMIT,
            ApplicationStatus.BLOCKED,
        }
    ),
    ApplicationStatus.READY_TO_SUBMIT: frozenset(
        {ApplicationStatus.SUBMITTED, ApplicationStatus.AWAITING_REVIEW,
         ApplicationStatus.BLOCKED, ApplicationStatus.FAILED}
    ),
    ApplicationStatus.SUBMITTED: frozenset(),
    ApplicationStatus.FAILED: frozenset({ApplicationStatus.QUEUED}),
    ApplicationStatus.BLOCKED: frozenset({ApplicationStatus.QUEUED}),
}


class InvalidTransitionError(ValueError):
    """Raised when an application status transition is not allowed."""


@dataclass
class JobPosting:
    """A single job posting collected by the scout."""

    company: str
    title: str
    url: str
    location: str = ""
    posted_at: str = ""  # ISO date/datetime; parsed by scout.is_fresh
    source: str = "job_board"  # "job_board" | "university"
    track: str = ""  # primary | secondary | extended | selective | ""
    verified: bool = False
    verification_note: str = ""
    remote: bool = False
    flags: list[str] = field(default_factory=list)
    match_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobPosting":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ATSResult:
    """Result of the deterministic JD scoring in ats.score_jd."""

    score: int  # 0-100
    band: str  # priority | recommend | low_priority | skip
    matched: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Application:
    """An application tracked through the submitter pipeline."""

    company: str
    title: str
    url: str = ""
    track: str = ""
    ats_score: int | None = None
    status: ApplicationStatus = ApplicationStatus.QUEUED
    applied_at: str = ""
    confirmation_no: str = ""
    notes: str = ""
    id: int | None = None

    def transition(self, new_status: ApplicationStatus) -> None:
        """Move to ``new_status``; raises InvalidTransitionError if illegal."""
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {self.status.value} -> {new_status.value}"
            )
        self.status = new_status
        if new_status is ApplicationStatus.SUBMITTED and not self.applied_at:
            self.applied_at = (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )

    def can_auto_submit(self) -> bool:
        """Whether this application may be submitted without another review."""
        return self.status is ApplicationStatus.READY_TO_SUBMIT

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Application":
        data = dict(data)
        if "status" in data and isinstance(data["status"], str):
            data["status"] = ApplicationStatus(data["status"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
