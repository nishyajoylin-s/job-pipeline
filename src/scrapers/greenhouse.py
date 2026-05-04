"""Greenhouse adapter. Public API: fetch(company) -> list[NormalizedJob]."""
from ._base import NormalizedJob, http_get_json

SOURCE = "greenhouse"
BASE = "https://boards-api.greenhouse.io/v1/boards"


def fetch(company: str) -> list[NormalizedJob]:
    data = http_get_json(f"{BASE}/{company}/jobs?content=true")
    return [
        NormalizedJob(
            source=SOURCE,
            external_id=str(job["id"]),
            company=company,
            title=job["title"],
            location=(job.get("location") or {}).get("name"),
            url=job["absolute_url"],
            jd_text=job.get("content"),
            updated_at=job.get("updated_at"),
            raw=job,
        )
        for job in data["jobs"]
    ]