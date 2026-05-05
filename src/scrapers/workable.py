"""Workable adapter. Public widget API per company subdomain.

Endpoint: https://apply.workable.com/api/v1/widget/accounts/{subdomain}
Returns: {"name": str, "description": str, "jobs": [...]}

Note: the widget endpoint returns listings without JD text. Adding
descriptions would require an additional fetch per job. For now,
adapter returns NormalizedJob with empty jd_text. Stack and leadership
scoring will be 0 for Workable jobs until per-job fetching is added.

Multi-location jobs: the `locations` array contains one entry per
location. We join them with semicolons so the location scorer can
pick up any matching city.
"""
from ._base import NormalizedJob, http_get_json

SOURCE = "workable"
BASE = "https://apply.workable.com/api/v1/widget/accounts"


def fetch(company: str) -> list[NormalizedJob]:
    data = http_get_json(f"{BASE}/{company}")

    return [
        NormalizedJob(
            source=SOURCE,
            # shortcode is Workable's stable 10-char public id (e.g. "488EEDF86E").
            external_id=job["shortcode"],
            company=company,
            title=job["title"],
            location=_location(job),
            url=job["url"],
            jd_text=None,  # not in widget endpoint; per-job fetch needed
            updated_at=job.get("created_at") or job.get("published_on"),
            raw=job,
        )
        for job in data.get("jobs", [])
    ]


def _location(job: dict) -> str | None:
    """Workable returns location as flat country/city/state plus a `locations[]`
    array for multi-location jobs. Prefer the array as source of truth."""
    locations = job.get("locations") or []
    if locations:
        parts = [
            ", ".join(p for p in [loc.get("city"), loc.get("country")] if p)
            for loc in locations
        ]
        parts = [p for p in parts if p]
        if job.get("telecommuting"):
            parts.insert(0, "Remote")
        return "; ".join(parts) if parts else None

    # Fallback to flat fields if locations[] is empty
    parts = [job.get("city"), job.get("state"), job.get("country")]
    joined = ", ".join(p for p in parts if p)
    if job.get("telecommuting"):
        joined = f"Remote{', ' + joined if joined else ''}"
    return joined or None