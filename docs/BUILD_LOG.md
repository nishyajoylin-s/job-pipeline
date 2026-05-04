# Build log

A chronological record of what was built when, what was deferred, and what was learned along the way.

## Day 1. ATS scrapers, scoring, storage

**Goal.** Get a useful working dataset of senior data leadership postings from the web into a queryable store, with a ranking function on top.

**Built.**

- Four ATS adapters (Greenhouse with dual URL formats, Lever, Ashby, Personio) sharing a registry pattern in `src/scrapers/__init__.py`
- `NormalizedJob` pydantic model as the trust boundary, in `src/scrapers/_base.py`. Adapters cannot return raw API payloads
- SQLite schema with a hash-based primary key (`sha256(source:external_id)[:16]`) and `INSERT OR IGNORE` upsert. Re-runs are no-ops on existing rows
- Pure scoring function in `src/score.py` across six dimensions (role, seniority, stack, location, leadership cues, language) with explicit per-dimension reasons returned alongside the total
- Hard junior-kill filter in `src/rank.py`, separated from scoring on purpose so rules and policy can evolve independently
- CLI runners (`main.py`, `rank.py`) for scrape and rank

**Outcomes.**

- 4005 jobs across roughly 30 companies. US tech, DACH and EU, plus a long tail of remote
- Top hit at end of Day 1 was a "Lead AI Solutions" role in Munich at score 69
- Zero "Head of Data" matches across the entire dataset. Public ATS feeds materially underrepresent senior leadership roles. Useful insight, not a bug

**Deferred.**

- Email digest. Day 2 work
- More ATS adapters (Workable, SmartRecruiters, Workday). Day 3 and beyond
- Status column for posting triage. Future
- LLM-tailored CV per posting. Out of scope

## Day 2. Email digest

**Goal.** Ship one focused capability. A daily email containing the top 25 unsent matches.

**Discipline.** Time-boxed to 90 minutes across four steps. No new sources, no new scoring dimensions, no GitHub Actions or dashboards. Scope discipline matters more than feature breadth on a learning-oriented project because every detour delays the next reusable building block.

**Built.**

- `templates/digest.html`. Jinja2 template with minimal markup. Email-client-safe basics (single column, system fonts, generous tap targets) but no inline-style polish, table-based layout, or dark-mode media queries. The tradeoff was made explicit. For one inbox, polish is wasted effort
- `src/digest.py`. Five stages in one file
    1. Query top 25 unsent jobs via `select_top_jobs(only_unsent=True)` from `rank.py`
    2. Enrich each with a stripped, truncated `jd_preview` (HTML stripped, unescaped to a fixed point, cut at the last word boundary inside 240 chars)
    3. Render the template with autoescape on
    4. Send via Resend using the `onboarding@resend.dev` sandbox sender so v0 needs no domain verification
    5. Stamp `notified_at` in one `executemany` transaction, only after a successful send, so a network blip means the next run retries
- `--dry-run` flag. Renders the template to `output/last_digest.html` and skips both the send and the flag write. The same write happens on real sends too, so the most recent rendered output is always inspectable. Iteration is safe. Burning the `notified_at` flag on a bad first render would have lost 25 jobs from the next real send
- Pre-flight env-var check. Fail-fast with a clear message rather than failing inside the Resend call

**Bugs found and fixed.**

- JD previews showed literal `&lt;` and `&gt;` characters. Source data was HTML-entity-encoded, and the strip-HTML regex never matched because there were no real angle brackets. Fixed by running `html.unescape` before the tag regex
- Some content was double-encoded (`&amp;amp;`, `&amp;nbsp;`). A single `html.unescape` call only peeled one layer. Replaced with a fixed-point loop capped at three passes

**Outcomes.**

- 25 jobs delivered to inbox, full pipeline working from scrape through to send
- Top hit at end of Day 2 was a "Staff Data Analyst, AI Tooling" role at score 75. The Day 1 leader moved to position two

**Known weaknesses surfaced during testing.**

- The scorer can rank non-data leadership roles high when the title does not match the data pattern but every other dimension does. A Principal Enterprise Architect role landed in the top five with `role=0`. Tracked for Day 3 tuning
- Location penalty of -12 is not strong enough to push US or Brazil postings out of the top five when role and seniority dimensions are full. Tracked
- "Staff data" pattern matches IC roles like "Staff Data Scientist" as if they were leadership. Title matching needs tighter rules. Tracked

**Deferred to Day 3 and beyond.**

- More ATS adapters (Workable first, then SmartRecruiters and Workday)
- Scorer tuning to fix the false positives surfaced today
- Status column CLI for posting triage (`saved`, `watching`, `dismissed`)
- GitHub Actions schedule for nightly runs
- Embedding-based scoring once rules hit obvious limits
