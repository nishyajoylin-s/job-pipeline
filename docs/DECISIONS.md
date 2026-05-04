# Design decisions

Lightweight ADR format. One record per major call. Each captures the context that made the decision worth flagging, the decision itself, and the tradeoffs accepted.

## 1. SQLite for v0, Postgres later

**Context.** Need persistent storage with simple query patterns. Single user. Single machine. Volume is low (a few thousand rows per run, no concurrent writers).

**Decision.** SQLite via stdlib for now. Migration to Supabase Postgres planned when one of three triggers fires.

- Need to read the digest from a second device
- Need to share the job inventory with someone else
- Need full-text search on JDs that SQLite cannot do well

**Tradeoffs accepted.** Zero ops cost today. The migration path is documented and the schema is small enough that a one-shot dump-and-load is fine. A future second-device requirement will force the migration before it would otherwise be needed.

## 2. Rule-based scoring before embeddings

**Context.** Two ways to score a job against a target profile. Hand-written rules over keyword matches, or vector similarity using embeddings of the JD against an embedding of the profile.

**Decision.** Rules first. Six dimensions (role, seniority, stack, location, leadership cues, language) each scored independently with explicit weights. Embeddings reserved for Week 2 once the rules hit obvious limits.

**Tradeoffs accepted.** Every score is debuggable from the breakdown printed alongside it. When a wrong job ranks high, the dimension that produced the false positive is visible. Tuning is a code change, not a model retrain. Rules cannot read intent, so a "Solutions Engineer" role with "AI" in the title scores like an AI leadership role even when the JD is sales engineering. Tracked as a known weakness.

## 3. Adapter pattern with registry

**Context.** Four ATSes today, more planned (Workable, SmartRecruiters, Workday). Each has its own API shape and quirks.

**Decision.** One adapter file per ATS in `src/scrapers/`, registered in a `SCRAPERS` dict in `__init__.py`. Adding a new ATS is a one-file change plus one line of registration.

**Tradeoffs accepted.** Adding sources is mechanical. The runner (`main.py`) does not change. Per-adapter error handling is uniform. A small amount of boilerplate per adapter (HTTP setup, parsing, mapping to `NormalizedJob`). Worth it for the scaling pattern.

## 4. Pydantic at the trust boundary, plain dicts after

**Context.** External APIs return data of varying quality. Different ATSes use different field names, types, and conventions for missing data.

**Decision.** `NormalizedJob` is a pydantic model that all adapters must produce. After validation, the row is converted to a dict and every downstream module works with plain dicts.

**Tradeoffs accepted.** Validation surface is small (one model). Internal modules stay lightweight, do not depend on pydantic semantics, and are easy to mock in tests with plain dicts. A small mental model for contributors. Pydantic at source, dicts after. Documented inline in `_base.py`.

## 5. Hash-based primary key, INSERT OR IGNORE

**Context.** Re-running the scraper should be safe. We do not want duplicate jobs and we do not want to write a deduplication step.

**Decision.** Primary key is `sha256(source + ':' + external_id)[:16]`. Inserts use `INSERT OR IGNORE`, making re-runs no-ops on existing rows.

**Tradeoffs accepted.** Idempotency is structural rather than enforced by application logic. Cross-source uniqueness comes for free (a Greenhouse `12345` and a Lever `12345` produce different hashes). Title and JD changes upstream are silently dropped because we ignore rather than upsert. A proper change-data-capture loop is future work.

## 6. Resend over SMTP

**Context.** Need to send one email per day to one recipient. Could use SMTP via Gmail, AWS SES, or a transactional email service.

**Decision.** Resend. One HTTP call, one library, one API key. No MTA setup, no DKIM or SPF records to wrangle for v0.

**Tradeoffs accepted.** Free tier covers single-recipient volume. Sandbox sender (`onboarding@resend.dev`) works without a verified domain. Lock-in to one provider. The send call is wrapped in `send_email()` so swapping is a one-function change if the trigger comes (volume or deliverability).

## 7. Dry-run writes preview to disk

**Context.** Iterating on the email template against real data risks burning the `notified_at` flag for jobs the digest looked bad on, which then would not appear in the next real send.

**Decision.** `--dry-run` writes the rendered HTML to `output/last_digest.html` and skips both the send and the `notified_at` update. The same write happens on real sends too, so the most recent rendered output is always inspectable.

**Tradeoffs accepted.** Iteration is safe. "What did the last digest look like?" is answerable without re-querying the DB. One filesystem write per run. Negligible.

## 8. Notification flag write happens after a successful send

**Context.** Marking a job as notified before sending risks losing it to a network blip. Marking after sending risks duplicates if the DB write fails.

**Decision.** Send first, then write `notified_at` in a single `executemany` transaction. A failure to write the flag means a duplicate digest next run.

**Tradeoffs accepted.** Duplicate emails are recoverable. A missed role is not. Picked the recoverable failure mode.
