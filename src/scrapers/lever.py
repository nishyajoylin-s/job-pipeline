"""Lever adapter. Lever returns a top-level JSON array, not a wrapped object."""
from ._base import NormalizedJob, http_get_json

SOURCE = "lever"
BASE = "https://api.lever.co/v0/postings"


def fetch(company: str) -> list[NormalizedJob]:
    data = http_get_json(f"{BASE}/{company}?mode=json")
    # Lever returns a list directly, not {"jobs": [...]}
    return [
        NormalizedJob(
            source=SOURCE,
            external_id=str(job["id"]),
            company=company,
            title=job["text"],
            location=(job.get("categories") or {}).get("location"),
            url=job["hostedUrl"],
            jd_text=job.get("descriptionPlain") or job.get("description"),
            updated_at=str(job.get("createdAt", "")),  # Lever uses ms epoch, kept as string for now
            raw=job,
        )
        for job in data
    ]