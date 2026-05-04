# Architecture

This document describes how the pipeline is laid out, what each module owns, how data flows through it, and how failure is contained.

## Module responsibilities

| File | Role |
|---|---|
| `main.py` | Entry. Iterates the `SCRAPERS` registry, calls each adapter, upserts results. |
| `src/scrapers/__init__.py` | Registry. Maps source name to adapter function. |
| `src/scrapers/_base.py` | `NormalizedJob` pydantic model and shared HTTP helper. |
| `src/scrapers/<ats>.py` | One adapter per ATS. Fetches, parses, yields `NormalizedJob`. |
| `src/db.py` | SQLite schema, idempotent upsert, stats. |
| `src/score.py` | Pure scoring. Six dimensions, rule-based. No I/O. |
| `src/rank.py` | Query DB, score each row, return top N as enriched dicts. |
| `src/digest.py` | Render template, send via Resend, mark `notified_at`. |
| `templates/digest.html` | Jinja2 template. Dumb. All formatting decisions live in Python. |

## Data flow

A run goes through five stages.

**Fetch.** `main.py` walks the `SCRAPERS` dict and calls each adapter. Adapters fetch from the ATS over HTTP for JSON sources or via lxml for the Personio XML feed. Per-source errors are caught at the registry level so one broken source never crashes the whole run.

**Normalize.** Each adapter yields `NormalizedJob`, a pydantic model that asserts the contract every downstream stage relies on. Different ATSes return different shapes (Greenhouse and Lever look nothing alike), but the model collapses them to one schema.

**Persist.** `src/db.py` accepts the model and writes to SQLite via `INSERT OR IGNORE`. The primary key is a 16-character hex hash of `source:external_id`, so re-runs on existing jobs no-op cleanly.

**Score.** `src/score.py` is a pure function. It takes a job dict and returns `(int, dict)` with total and per-dimension reasons. No DB access. No env reads. This makes it trivially unit-testable, and lets `rank.py` decide separately whether to apply hard filters.

**Rank and emit.** `src/rank.py` pulls candidates from SQLite, applies `is_junior_kill` as a hard filter, scores the rest, sorts. `src/digest.py` enriches each top-N job with a stripped JD preview, renders the Jinja template, sends via Resend, then stamps `notified_at` only on success.

## Trust boundary

External data is treated as untrusted until validated. Scrapers cannot return raw API payloads. They must produce `NormalizedJob` instances. After that point, every internal function works with plain dicts converted from validated rows. No pydantic objects flow past the scraper layer.

This split has two benefits. The validation surface is small and explicit (one model, one place). And internal code stays lightweight because dict access is faster and easier to mock in tests than pydantic model access.

## Database schema

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,    -- sha256(source:external_id)[:16]
    source        TEXT NOT NULL,       -- 'greenhouse', 'lever', 'ashby', 'personio'
    external_id   TEXT NOT NULL,       -- ATS-internal job id
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    url           TEXT NOT NULL,
    jd_html       TEXT,                -- raw description, possibly entity-encoded
    updated_at    TEXT,
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    notified_at   TEXT,                -- set after successful digest send
    status        TEXT DEFAULT 'discovered'
);
CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);
```

The `status` column is reserved for posting triage (saved, watching, dismissed). Default value is `discovered`.

## Failure modes and what catches them

**Source goes down.** Per-adapter try/except in `main.py` logs and continues. Other sources still scrape.

**Schema drift at the source.** Pydantic raises on missing or wrong-typed fields at the boundary. The bad row is dropped, the rest of the source continues. Loud failure beats silent corruption.

**Re-running on existing data.** `INSERT OR IGNORE` on the hash PK. Re-runs are no-ops on unchanged rows.

**Resend send fails.** `notified_at` is only stamped after `resend.Emails.send` returns successfully. The next run will retry the same jobs.

**Resend succeeds but DB write fails.** Rare. Result is a duplicate digest on next run. Selected this tradeoff over the inverse (lose a notification), because duplicate emails are recoverable and missed roles are not.

**Title-keyword false positives.** `_word_hits` in `score.py` uses regex word boundaries so "staff data" no longer matches "staff database engineer" and similar near-misses.

**Doubly entity-encoded JDs.** `_strip_html` in `digest.py` runs `html.unescape` in a loop until stable. Some ATSes return JD content that is encoded twice (`&amp;amp;` then again).

## Patterns enforced deliberately

- Filters separated from scoring. Scoring is pure rules. Filters are policy. They evolve at different rates so they live in different functions.
- Template kept dumb. All formatting (HTML stripping, truncation, preview generation) happens in Python where it can be tested.
- No private-helper imports across modules. `_strip_html` is duplicated between `score.py` and `digest.py` because importing a private from another module is worse than three lines of duplication.
- Idempotency is structural rather than checked. The hash PK plus `INSERT OR IGNORE` makes re-runs safe by construction, not by guarded application code.
