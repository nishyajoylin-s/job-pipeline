"""Tests for src.rank.select_top_jobs. Mocks DB to verify filter behavior."""
from __future__ import annotations

from unittest.mock import patch

from src import rank


def _row(**fields):
    """Minimal sqlite3.Row-like object. select_top_jobs treats it as a dict."""
    base = {
        "id": "x",
        "source": "test",
        "company": "TestCo",
        "title": "",
        "location": "",
        "url": "https://example.com/j/1",
        "jd_html": "",
    }
    base.update(fields)
    return base


def test_role_zero_jobs_filtered_out():
    """role=0 jobs (e.g. Principal Enterprise Architect) should not appear in
    top results regardless of how strong other dimensions are."""
    rows = [
        _row(id="1", title="Principal Enterprise Architect",
             location="Munich", jd_html="dbt Power BI"),
        _row(id="2", title="Head of Data", location="Munich"),
    ]
    with patch.object(rank, "connect") as mock_connect:
        mock_connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = rows
        result = rank.select_top_jobs(limit=10)

    titles = [r["title"] for r in result]
    assert "Principal Enterprise Architect" not in titles
    assert "Head of Data" in titles