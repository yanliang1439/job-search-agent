"""Preparer: resume truthfulness guards.

Implements the authenticity red lines from the preparer brief. Every rule is
a pure function over resume text returning human-readable violations:

1. The Weibo title must be "Senior Data Analyst" — never
   "Senior Data Scientist".
2. "No sponsorship required" must never appear on the resume (it belongs only
   in application-form answers).
3. The header must contain "Authorized to work in the U.S."
4. SAS may only appear as "SAS (undergraduate coursework)" — proficiency
   must never be claimed.
5. No GPA on the resume.
6. Graduation must read "Expected Jun 2027"; "Dec 2026" is forbidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ResumeViolation:
    rule: str
    detail: str
    suggestion: str = ""

    def __str__(self) -> str:
        base = f"[{self.rule}] {self.detail}"
        return f"{base} -> {self.suggestion}" if self.suggestion else base


_GPA_RE = re.compile(r"\bGPA\b\s*[:：]?\s*\d(?:\.\d+)?", re.IGNORECASE)
_DEC2026_RE = re.compile(
    r"\bDec(?:ember)?\s+2026\b|\b2026[\s\-/年]12\b|\b12/2026\b", re.IGNORECASE
)
_EXPECTED_JUN2027_RE = re.compile(
    r"Expected\s+Jun(?:e)?\s+2027|Jun(?:e)?\s+2027", re.IGNORECASE
)


def check_resume_text(text: str) -> list[ResumeViolation]:
    """Check resume text against all truthfulness guards.

    Returns the list of violations; empty means the resume passes.
    """
    violations: list[ResumeViolation] = []
    low = text.lower()

    # Rule 1: Weibo title.
    if "senior data scientist" in low and "weibo" in low:
        violations.append(
            ResumeViolation(
                rule="weibo_title",
                detail='Found "Senior Data Scientist" near a Weibo mention.',
                suggestion='Use "Senior Data Analyst" for the Sina Weibo role.',
            )
        )

    # Rule 2: no "No sponsorship required" on the resume.
    if "no sponsorship required" in low:
        violations.append(
            ResumeViolation(
                rule="sponsorship_phrase",
                detail='Resume contains "No sponsorship required".',
                suggestion="Remove it; sponsorship answers belong only in "
                "application forms.",
            )
        )

    # Rule 3: header must authorize work.
    if "authorized to work in the u.s." not in low:
        violations.append(
            ResumeViolation(
                rule="work_authorization_header",
                detail='Resume header is missing "Authorized to work in the U.S.".',
                suggestion='Add "Authorized to work in the U.S." to the header.',
            )
        )

    # Rule 4: SAS only as undergraduate coursework.
    sas_mentions = [
        m for m in re.finditer(r"\bSAS\b", text)
    ]
    for m in sas_mentions:
        window = text[max(0, m.start() - 60): m.end() + 60]
        if "undergraduate coursework" not in window.lower():
            violations.append(
                ResumeViolation(
                    rule="sas_claim",
                    detail=f'SAS appears without the required qualifier: "...{window.strip()}..."',
                    suggestion='Write it only as "SAS (undergraduate coursework)".',
                )
            )
            break  # one violation per resume is enough

    # Rule 5: no GPA on the resume.
    if _GPA_RE.search(text):
        violations.append(
            ResumeViolation(
                rule="gpa_on_resume",
                detail="Resume contains a GPA figure.",
                suggestion="Remove GPA from the resume; fill it in application "
                "forms only when asked.",
            )
        )

    # Rule 6: graduation timing.
    if _DEC2026_RE.search(text):
        violations.append(
            ResumeViolation(
                rule="graduation_dec2026",
                detail="Resume mentions Dec 2026 graduation.",
                suggestion="Graduation is fixed at Expected Jun 2027; Dec 2026 "
                "must never appear.",
            )
        )
    elif not _EXPECTED_JUN2027_RE.search(text):
        violations.append(
            ResumeViolation(
                rule="graduation_missing",
                detail='No "Expected Jun 2027" graduation date found.',
                suggestion="State graduation as Expected Jun 2027.",
            )
        )

    return violations


def resume_passes(text: str) -> bool:
    """Convenience wrapper: True when there are no violations."""
    return not check_resume_text(text)
