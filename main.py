"""Entry point. Iterates the scraper registry, loads everything to the DB."""
import requests
from pydantic import ValidationError

from src.db import init_db, upsert_job, count_jobs
from src.scrapers import SCRAPERS

# Companies to scrape, keyed by which source hosts their careers page.
# Add freely; one bad entry doesn't block the others.
TARGETS: dict[str, list[str]] = {
    "greenhouse": [
        "stripe", "airbnb", "anthropic", "figma", "databricks",
        "celonis", "sumup", "contentful", "n26", "gitlab",
        "raisin",
    ],
    "lever": [
        "spotify", "qonto", "contentsquare",
    ],
    "ashby": [
        "notion", "ramp", "linear",
        "tacto", "luminovo",
    ],
    "personio": [
        "1komma5grad",
        "cosuno",
        "moss",
        "forto",
        "urlaubsguru",
        "konux",
        "enpal",
        "alasco",
        "langdock",
        "solarisbank",
        "tier",
        "holidu",
    ],
    "workable": [
        "treatwell",
        "usercentrics",
        "workmotion",
    ],
    "smartrecruiters": [
        "continental",
        "visa",

    ],
}


def scrape(source: str, company: str) -> tuple[int, int]:
    jobs = SCRAPERS[source](company)
    new = sum(upsert_job(job) for job in jobs)
    return len(jobs), new


def main() -> None:
    init_db()
    print(f"Starting with {count_jobs()} jobs\n")

    for source, companies in TARGETS.items():
        for company in companies:
            label = f"{source}/{company}"
            try:
                total, new = scrape(source, company)
                print(f"{label:30} → {total:4} fetched, {new:4} new")
            except requests.HTTPError as e:
                # Some HTTPErrors are manually raised without a response attached.
                # Defensive access — never assume response exists.
                status = e.response.status_code if e.response is not None else "?"
                print(f"{label:30} → HTTP {status}")
            except requests.Timeout:
                print(f"{label:30} → TIMEOUT")
            except ValidationError as e:
                # Pydantic caught a source returning unexpected data.
                # Real-world: log and skip, don't crash the run.
                print(f"{label:30} → SCHEMA MISMATCH: {e.error_count()} errors")

    print(f"\nTotal: {count_jobs()} jobs")


if __name__ == "__main__":
    main()