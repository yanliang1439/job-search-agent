"""Tests for resume truthfulness guards."""

from jobagent import preparer

CLEAN = """Alex Rivera
Authorized to work in the U.S.
Sina Weibo — Senior Data Analyst, Advertising Analytics, Beijing
M.S. Computer Science, UC Davis — Expected Jun 2027
Skills: SQL, Python, Tableau. SAS (undergraduate coursework).
"""


def rules(violations):
    return {v.rule for v in violations}


def test_clean_resume_passes():
    assert preparer.check_resume_text(CLEAN) == []
    assert preparer.resume_passes(CLEAN)


def test_weibo_title_violation():
    text = CLEAN.replace("Senior Data Analyst", "Senior Data Scientist")
    assert "weibo_title" in rules(preparer.check_resume_text(text))


def test_sponsorship_phrase_violation():
    text = CLEAN + "\nNo sponsorship required.\n"
    assert "sponsorship_phrase" in rules(preparer.check_resume_text(text))


def test_missing_authorization_header():
    text = CLEAN.replace("Authorized to work in the U.S.\n", "")
    assert "work_authorization_header" in rules(preparer.check_resume_text(text))


def test_sas_without_qualifier():
    text = CLEAN.replace("SAS (undergraduate coursework)", "SAS, advanced")
    assert "sas_claim" in rules(preparer.check_resume_text(text))


def test_gpa_violation():
    text = CLEAN + "\nGPA: 3.78\n"
    assert "gpa_on_resume" in rules(preparer.check_resume_text(text))


def test_dec2026_violation():
    text = CLEAN.replace("Expected Jun 2027", "Dec 2026")
    vs = preparer.check_resume_text(text)
    assert "graduation_dec2026" in rules(vs)


def test_missing_graduation():
    text = CLEAN.replace("Expected Jun 2027", "2027")
    assert "graduation_missing" in rules(preparer.check_resume_text(text))


def test_multiple_violations_reported():
    text = "Senior Data Scientist at Weibo\nGPA 3.9\n"
    vs = preparer.check_resume_text(text)
    assert len(vs) >= 2
