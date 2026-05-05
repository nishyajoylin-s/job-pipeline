"""Pure ranking: query DB, score, filter, return top N.
Importable from anywhere in the project. CLI lives in /rank.py at root."""
from src.db import connect
from src.score import score, is_junior_kill


def select_top_jobs(limit: int = 25, only_unsent: bool = False) -> list[dict]:
    """Return top-scored jobs as a list of dicts, each enriched with score + breakdown.

    only_unsent: if True, filter to jobs where notified_at IS NULL.
                 Used by the digest to skip already-emailed jobs.
                 The junior-kill filter is applied in Python because it's a
                 regex on title — pushing it to SQL would mean reimplementing
                 the regex in SQLite's LIKE syntax. Not worth it.
    """
    sql = "SELECT id, source, company, title, location, url, jd_html FROM jobs"
    params: tuple = ()
    if only_unsent:
        sql += " WHERE notified_at IS NULL"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    scored: list[tuple[int, dict, dict]] = []
    for row in rows:
        job = dict(row)
        if is_junior_kill(job["title"]):
            continue
        total, why = score(job)
        # Filter role=0 jobs. They lack any data/leadership signal in the title.
        # A non-data Principal/Architect can otherwise accumulate 50+ points
        # via seniority + stack + location. Filter is policy, lives here, not in score.py.
        if why["subtotals"]["role"] == 0:
            continue
        scored.append((total, why, job))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Flatten into a single dict per job so the template doesn't unpack tuples.
    # Templates that index into tuples are awful to debug.
    return [
        {**job, "total": total, "why": why}
        for total, why, job in scored[:limit]
    ]