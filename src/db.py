"""SQLite storage for jobs."""
import hashlib
import sqlite3
from pathlib import Path

from src.scrapers import NormalizedJob

# DB file lives at the project root, not inside src/
DB_PATH = Path(__file__).parent.parent / "jobs.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id            TEXT PRIMARY KEY,
                source        TEXT NOT NULL,
                external_id   TEXT NOT NULL,
                company       TEXT NOT NULL,
                title         TEXT NOT NULL,
                location      TEXT,
                url           TEXT NOT NULL,
                jd_html       TEXT,
                updated_at    TEXT,
                discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                notified_at   TEXT,
                status        TEXT DEFAULT 'discovered'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")


def make_id(source: str, external_id: str) -> str:
    raw = f"{source}:{external_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def upsert_job(job: NormalizedJob) -> bool:
    """Insert a NormalizedJob, or ignore if already present.
    Returns True if newly inserted. Accepts the model (not kwargs) so schema
    changes only touch this function, not every call site."""
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, source, external_id, company, title, location, url, jd_html, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id(job.source, job.external_id),
                job.source,
                job.external_id,
                job.company,
                job.title,
                job.location,
                str(job.url),          # pydantic HttpUrl -> str for sqlite
                job.jd_text,
                job.updated_at,
            ),
        )
        return cursor.rowcount > 0


def count_jobs() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def stats():
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        print(f"Total jobs: {total}\n")

        print("By source/company:")
        for row in conn.execute(
            """
            SELECT source, company, COUNT(*) AS n
            FROM jobs
            GROUP BY source, company
            ORDER BY source, n DESC
            """
        ):
            print(f"  {row['source']:12} {row['company']:16} {row['n']}")

        print("\nTitle keyword counts:")
        keywords = ["engineer", "data", "machine learning", "senior", "manager", "sales"]
        for kw in keywords:
            n = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE lower(title) LIKE ?",
                (f"%{kw}%",),
            ).fetchone()[0]
            print(f"  {kw:20} {n}")


if __name__ == "__main__":
    stats()