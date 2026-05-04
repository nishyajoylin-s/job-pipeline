"""Rank all jobs in the DB, applying the junior-kill filter.
Prints top N with breakdown + a distribution histogram for tuning."""
from src.db import connect
from src.score import score, is_junior_kill


TOP_N = 25


def main() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, source, company, title, location, url, jd_html FROM jobs"
        ).fetchall()

    scored = []
    killed = 0
    for row in rows:
        job = dict(row)
        if is_junior_kill(job["title"]):
            killed += 1
            continue
        total, why = score(job)
        scored.append((total, why, job))

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"Scored {len(scored)} jobs ({killed} junior/intern/associate filtered out)\n")
    print(f"Top {TOP_N}:\n")
    for total, why, job in scored[:TOP_N]:
        sub = why["subtotals"]
        print(f"[{total:3}] {job['company'][:30]:30} | {job['title'][:60]}")
        print(f"       {job['location']}")
        print(f"       {job['url']}")
        print(f"       role={sub['role']} sen={sub['seniority']} stack={sub['stack']} "
              f"loc={sub['location']} lead={sub['leadership']} lang={sub['lang_penalty']}")
        print(f"       role: {why['role']}")
        print(f"       stack: {why['stack']}")
        if sub["lang_penalty"] < 0:
            print(f"       ⚠️  {why['language']}")
        print()

    # Distribution
    buckets = {"0-9": 0, "10-29": 0, "30-49": 0, "50-69": 0, "70-89": 0, "90-100": 0}
    for total, _, _ in scored:
        if total < 10: buckets["0-9"] += 1
        elif total < 30: buckets["10-29"] += 1
        elif total < 50: buckets["30-49"] += 1
        elif total < 70: buckets["50-69"] += 1
        elif total < 90: buckets["70-89"] += 1
        else: buckets["90-100"] += 1

    print("Score distribution (post-filter):")
    max_n = max(buckets.values()) or 1
    for k, v in buckets.items():
        bar = "█" * (v * 40 // max_n)
        print(f"  {k:8} {v:5}  {bar}")


if __name__ == "__main__":
    main()