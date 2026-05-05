"""Tests for src.score. Locks current scoring behavior so tuning has feedback.

Each test follows arrange-act-assert. We construct a job dict, call score(),
and assert on either the total or a specific subtotal.

Test cases are organized by what they verify:
- happy path (Munich senior data lead scores high)
- known false positives (role=0 ranks high — flag for tuning later)
- hard filter (junior_kill removes below-level)
- edge cases (empty fields, none values)
"""
from __future__ import annotations

import pytest

from src.score import score, is_junior_kill


def make_job(**overrides) -> dict:
    """Helper. Returns a baseline job dict with overridable fields.
    Keeps tests readable — only the fields under test need to appear."""
    base = {
        "title": "",
        "location": "",
        "jd_html": "",
    }
    return {**base, **overrides}


# -------- HAPPY PATH --------

def test_munich_head_of_data_scores_high():
    job = make_job(
        title="Head of Data",
        location="Munich, Germany",
        jd_html="We need someone to lead a team of data engineers using dbt and Power BI.",
    )
    total, why = score(job)
    assert total >= 70, f"expected >=70, got {total}: {why}"
    assert why["subtotals"]["role"] == 40
    assert why["subtotals"]["seniority"] == 25
    assert why["subtotals"]["location"] == 15


def test_senior_analytics_engineer_munich_scores_well():
    job = make_job(
        title="Senior Analytics Engineer",
        location="Munich, Germany",
        jd_html="dbt, Power BI, A/B testing, governance, stakeholder management.",
    )
    total, _ = score(job)
    assert 50 <= total <= 80, f"expected 50-80, got {total}"


# -------- LOCATION PENALTIES --------

def test_us_location_penalty_applied():
    job = make_job(
        title="Principal Data Scientist",
        location="San Francisco, California",
        jd_html="",
    )
    _, why = score(job)
    assert why["subtotals"]["location"] == -25, why["location"]


def test_remote_eu_scores_modest():
    job = make_job(
        title="Senior Data Engineer",
        location="Remote - EU",
    )
    _, why = score(job)
    assert why["subtotals"]["location"] == 7


def test_no_location_returns_zero():
    job = make_job(title="Data Engineer", location=None)
    _, why = score(job)
    assert why["subtotals"]["location"] == 0


# -------- KNOWN FALSE POSITIVES (locked, fix in scorer-tuning task) --------

def test_principal_enterprise_architect_currently_outranks_role_zero_signal():
    """Celonis case from Day 2. role=0 case; scorer still produces a
    non-zero total but rank.py filters role=0 jobs from results.
    This test asserts the scorer behavior; rank-level filter tested separately."""
    job = make_job(
        title="Principal Enterprise Architect",
        location="Munich, Germany",
        jd_html="dbt Power BI dimensional modeling stakeholder",
    )
    total, why = score(job)
    assert why["subtotals"]["role"] == 0
    # Scorer still adds non-role dimensions; the filter happens at rank time.
    assert total > 0

def test_staff_data_scientist_currently_matches_tech_lead():
    """'Staff Data Scientist' is an IC role. After Day 3 tuning, senior-IC
        bucket is checked before tech-lead so the more specific match wins."""
    job = make_job(title="Staff Data Scientist", location="Berlin, Germany")
    _, why = score(job)
    assert why["subtotals"]["role"] == 20, "if this fails, scorer was tuned"


# -------- HARD FILTER (is_junior_kill) --------

@pytest.mark.parametrize("title", [
    "Junior Data Engineer",
    "Werkstudent Data Analyst",
    "Data Engineering Intern",
    "Associate Analytics Engineer",
    "Trainee Data Scientist",
])
def test_junior_titles_killed(title):
    assert is_junior_kill(title) is True


@pytest.mark.parametrize("title", [
    "Senior Data Engineer",
    "Head of Data",
    "Lead Analytics Engineer",
    "Principal Data Scientist",
])
def test_senior_titles_pass(title):
    assert is_junior_kill(title) is False


# -------- LANGUAGE PENALTY --------

def test_business_german_required_triggers_penalty():
    job = make_job(
        title="Senior Data Engineer",
        location="Munich, Germany",
        jd_html="Fluent German required. C1 German minimum.",
    )
    _, why = score(job)
    assert why["subtotals"]["lang_penalty"] == -10


def test_no_german_requirement_no_penalty():
    job = make_job(
        title="Senior Data Engineer",
        location="Munich, Germany",
        jd_html="English-speaking team.",
    )
    _, why = score(job)
    assert why["subtotals"]["lang_penalty"] == 0


# -------- EDGE CASES --------

def test_empty_job_does_not_crash():
    total, why = score(make_job())
    assert total == 0
    assert why["subtotals"]["role"] == 0


def test_negative_role_via_negative_keyword():
    """Sales/recruiter titles get negative role even with 'data' in title."""
    job = make_job(title="Sales Director - Data Tools", location="Munich")
    _, why = score(job)
    assert why["subtotals"]["role"] <= 0