"""SmartRecruiters adapter. Public postings API per company.

Endpoint: https://api.smartrecruiters.com/v1/companies/{company}/postings
Returns: {"offset": int, "limit": int, "totalFound": int, "content": [...]}

Listing returns metadata only. JD text requires a per-job fetch at
/postings/{id}, deferred for now (jd_text=None). Stack and leadership
scoring will be 0 for SmartRecruiters jobs until per-job fetching is added.

Pagination: SmartRecruiters caps limit at 100. We page through until
we've collected all totalFound. Continental alone is 1200+ jobs.
Be aware: many large enterprises post a long tail of non-data roles
(manufacturing, retail, ops). Rule-based scoring filters them out so
the database grows but digest quality is unaffected.
"""
from ._base import NormalizedJob, http_get_json

SOURCE = "smartrecruiters"
BASE = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100


def fetch(company: str) -> list[NormalizedJob]:
    jobs: list[NormalizedJob] = []
    offset = 0
    while True:
        url = f"{BASE}/{company}/postings?limit={PAGE_SIZE}&offset={offset}"
        data = http_get_json(url)
        content = data.get("content", [])
        if not content:
            break
        for posting in content:
            jobs.append(_normalize(posting, company))
        offset += PAGE_SIZE
        # totalFound tells us when we've drained the source. Break before issuing
        # a wasted call for an empty page.
        if offset >= data.get("totalFound", 0):
            break
    return jobs


def _normalize(posting: dict, company: str) -> NormalizedJob:
    # company.identifier is used in the public URL (case-sensitive on SR's side).
    # Fall back to the lowercase company slug if the field is missing.
    company_identifier = (posting.get("company") or {}).get("identifier") or company
    return NormalizedJob(
        source=SOURCE,
        external_id=str(posting["id"]),
        company=company,
        title=posting["name"],
        location=_location(posting),
        # SmartRecruiters public URL pattern. Redirects to the slug version automatically.
        url=f"https://jobs.smartrecruiters.com/{company_identifier}/{posting['id']}",
        jd_text=None,  # listing has no description; per-job fetch deferred
        updated_at=posting.get("releasedDate"),
        raw=posting,
    )


def _location(posting: dict) -> str | None:
    """SmartRecruiters location is a nested object. Prefer fullLocation when present.
    The `remote` and `hybrid` booleans are flagged so the location scorer can
    pick them up as remote-friendly roles."""
    loc = posting.get("location") or {}
    if loc.get("fullLocation"):
        result = loc["fullLocation"]
    else:
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        result = ", ".join(p for p in parts if p)
    if loc.get("remote"):
        result = f"Remote{', ' + result if result else ''}"
    elif loc.get("hybrid"):
        result = f"Hybrid{', ' + result if result else ''}"
    return result or None