"""Shared building blocks for all scrapers.
Underscore prefix = 'internal to this package, don't import from outside'."""
from __future__ import annotations

import requests
from pydantic import BaseModel, Field, HttpUrl


class NormalizedJob(BaseModel):
    """Source-agnostic representation of a job posting.
    Every adapter must produce this shape. Downstream code knows only this."""
    source: str                       # 'greenhouse' | 'lever' | 'ashby'
    external_id: str                  # the source's own ID (as string, sources disagree on type)
    company: str
    title: str
    location: str | None = None
    url: HttpUrl                      # pydantic validates it's a real URL
    jd_text: str | None = None        # plain text or HTML, we'll clean later
    updated_at: str | None = None     # ISO string, kept as-is for now
    raw: dict = Field(default_factory=dict, exclude=True)  # original payload for debugging, not persisted


def http_get_json(url: str, *, timeout: int = 10) -> dict | list:
    """Single place for HTTP GETs. Consistent timeout, error handling, user-agent.
    When we add retries/backoff later, it's one edit, not N."""
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "job-pipeline (personal project)"},
    )
    response.raise_for_status()
    return response.json()