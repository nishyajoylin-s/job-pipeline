"""Personio adapter. Public XML feed per tenant at {tenant}.jobs.personio.de/xml

Design notes:
- Personio root element is <workzag-jobs> (legacy naming, stable across all tenants)
- Some tenants host multiple brands via <subcompany>; we prefer that over the
  URL-derived tenant name for the displayed company
- <additionalOffices> means one posting, multiple locations — we join them
- <jobDescriptions> is a list of sections (About, Responsibilities, Requirements);
  we concatenate into a single jd_text so downstream scoring has everything
"""
from __future__ import annotations

from lxml import etree

from ._base import NormalizedJob, http_get_json

SOURCE = "personio"
BASE_DE = "https://{tenant}.jobs.personio.de/xml"
BASE_COM = "https://{tenant}.jobs.personio.com/xml?language=en"


def fetch(tenant: str) -> list[NormalizedJob]:
    """Fetch all positions for one Personio tenant.
    `tenant` is the subdomain, e.g. '1komma5grad' for 1komma5grad.jobs.personio.de
    """
    # Personio XML isn't JSON — we need raw bytes, not http_get_json
    xml_bytes = _fetch_xml(tenant)
    root = etree.fromstring(xml_bytes)

    positions = root.findall("position")
    return [_parse_position(pos, tenant) for pos in positions]


def _fetch_xml(tenant: str) -> bytes:
    """Fetch raw XML bytes. Try .de first (default), fall back to .com (English)."""
    import requests
    for base in (BASE_DE, BASE_COM):
        url = base.format(tenant=tenant)
        try:
            response = requests.get(
                url,
                timeout=15,  # XML feeds can be large, longer timeout
                headers={"User-Agent": "job-pipeline (personal project)"},
            )
            if response.status_code == 200 and response.content:
                return response.content
        except requests.RequestException:
            continue
    # Construct a synthetic 404 response so main.py's error handling works uniformly.
    # Lesson: when raising HTTPError, always attach a response — calling code expects it.
    fake_response = requests.Response()
    fake_response.status_code = 404
    raise requests.HTTPError(
        f"Personio: tenant '{tenant}' not reachable on .de or .com",
        response=fake_response,
    )

def _parse_position(pos: etree._Element, tenant: str) -> NormalizedJob:
    """Convert one <position> element into a NormalizedJob.
    Helper does the XML→dict conversion; pydantic validates the result."""
    def text(path: str) -> str | None:
        """Get text content of a child element, None if missing/empty."""
        el = pos.find(path)
        return el.text.strip() if el is not None and el.text else None

    external_id = text("id")
    if not external_id:
        # Position without an ID is malformed; skip by raising — main.py catches it
        raise ValueError("Personio position missing <id>")

    # Prefer <subcompany> (real employer brand) over the URL-derived tenant name
    company = text("subcompany") or tenant

    # Office + additionalOffices/office → combined location string
    locations = [text("office")] if text("office") else []
    for extra in pos.findall("additionalOffices/office"):
        if extra.text:
            locations.append(extra.text.strip())
    location = ", ".join(dict.fromkeys(locations)) or None  # dedupe while preserving order

    # Concatenate all <jobDescription><value> sections into one text blob
    jd_parts = []
    for section in pos.findall("jobDescriptions/jobDescription"):
        name_el = section.find("name")
        value_el = section.find("value")
        if value_el is not None and value_el.text:
            heading = name_el.text.strip() if name_el is not None and name_el.text else ""
            jd_parts.append(f"<h3>{heading}</h3>{value_el.text}" if heading else value_el.text)
    jd_text = "\n".join(jd_parts) if jd_parts else None

    # Public URL for the job posting
    url = f"https://{tenant}.jobs.personio.de/job/{external_id}"

    return NormalizedJob(
        source=SOURCE,
        external_id=external_id,
        company=company,
        title=text("name") or "Untitled",
        location=location,
        url=url,
        jd_text=jd_text,
        updated_at=text("createdAt"),
        raw={},  # XML elements aren't JSON-serializable; skip raw storage
    )