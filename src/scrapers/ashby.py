"""Ashby adapter. Uses jobPostings wrapper; field names differ from Greenhouse."""
from ._base import NormalizedJob, http_get_json

SOURCE = "ashby"
BASE = "https://api.ashbyhq.com/posting-api/job-board"


def fetch(company: str) -> list[NormalizedJob]:
    # includeCompensation=true gets more useful data; harmless if unused
    data = http_get_json(f"{BASE}/{company}?includeCompensation=true")
    return [
        NormalizedJob(
            source=SOURCE,
            external_id=str(job["id"]),
            company=company,
            title=job["title"],
            location=job.get("locationName") or job.get("location"),
            url=job["jobUrl"],
            jd_text=job.get("descriptionHtml") or job.get("descriptionPlain"),
            updated_at=job.get("publishedAt"),
            raw=job,
        )
        for job in data["jobs"]
    ]