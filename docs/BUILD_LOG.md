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

## Day 3. Coverage expansion, tests, scorer tuning

**Goal.** Three sub-goals stretched the day rather than the one-focus discipline of Day 2. Add a fifth ATS adapter, lock current scoring behavior with tests, then tune the scorer to fix the false positives surfaced in Day 2.

**Built.**

- Workable adapter (`src/scrapers/workable.py`). Uses the public widget API at `apply.workable.com/api/v1/widget/accounts/<subdomain>`. The endpoint returns listings without JD text, so `jd_text=None` for Workable jobs and stack and leadership scoring stay at 0 for them until per-job fetching is added later
- pytest dev dependency and a `tests/` directory with 21 test cases covering the scorer (20) and rank-level filter (1). Two cases lock prior known false positives so future tuning has visible signal. Test file uses `pytest.mark.parametrize` for the junior-kill title patterns
- Scorer tuning to fix three patterns surfaced in Day 2.
    1. role=0 filter in `src/rank.py` removes non-data leadership roles (e.g. Principal Enterprise Architect) that previously accumulated 50+ points via seniority and stack alone. Filter lives at rank level because filters are policy and policy belongs separate from pure scoring rules
    2. Senior-IC patterns moved earlier in `score_role` so titles like "Staff Data Scientist" correctly score as IC (20) instead of being captured by the tech-lead bucket (30) via the loose "staff data" pattern. The more specific match wins
    3. Non-EU location penalty deepened from -12 to -25. A US Head of Data role at full strength previously scored 78 (still inside the top 25) and now lands at 65, reliably below DACH equivalents

**Coverage additions.**

- `gitlab` added to greenhouse (discovered to be on Greenhouse via careers-page source check)
- `holidu` added to personio (Munich-based travel tech, primary location match)
- `treatwell` added to workable (verification target with 68 active jobs)

**Outcomes.**

- Top result moved from "Staff Data Analyst, AI Tooling" at Qonto Paris (75) to "(Senior) Team Lead Data Analytics" at Holidu Munich (90). The new top hit is a real Munich senior data leadership posting
- Three Holidu Munich Senior Data Scientist roles cluster at 66, displacing previous US-based outliers
- Celonis Principal Enterprise Architect (Munich, role=0, total 64) no longer appears in the digest. The CLI debug output still shows it, which is intentional so the breakdown stays visible during tuning

**Discoveries.**

- The Workable widget endpoint returns 200 even for stub accounts that have no exposed jobs. Eleven candidates that returned 200 in the initial probe yielded zero active jobs across most of them. Status code alone is not a reliable signal for active integration
- Many DACH companies (e.g. holidu) use Personio rather than Workable. The probe-and-confirm pattern (one curl per ATS endpoint per candidate) is the cheapest way to find which ATS a target company uses

**Deferred to Day 4 and beyond.**

- GitHub Actions schedule for nightly digest runs
- Workday adapter. Each tenant has its own subdomain and cluster, so the SCRAPERS registry signature would need to change from `name → callable(company)` to `name → callable(company_config)`
- Per-job JD fetch for Workable so stack and leadership scoring works for those jobs
- SmartRecruiters and Recruitee adapters
- Embedding-based semantic scoring once rule-based scoring hits obvious limits

## Day 4. SmartRecruiters adapter, ATS-migration cleanup

**Goal.** Add a sixth ATS adapter covering large DACH enterprise. Fix Personio TARGETS that returned 404 by routing companies to their actual current ATS.

**Built.**

- SmartRecruiters adapter (`src/scrapers/smartrecruiters.py`). Public postings API at `api.smartrecruiters.com/v1/companies/<id>/postings`. Pagination via offset and limit, capped at 100 per page. Continental needed 13 pages for ~1210 jobs, which is the first time pagination has been required by any adapter
- Same listing-only constraint as Workable. `jd_text=None` for SmartRecruiters jobs, so stack and leadership scoring stays at 0 until per-job fetching is added

**Coverage additions and migrations.**

- `continental` added to smartrecruiters (~1210 jobs, German automotive tech)
- `visa` added to smartrecruiters (~39 jobs, fintech)
- `raisin` re-routed from personio (404) to greenhouse where they actually live now
- `usercentrics` re-routed from personio (404) to workable (21 active jobs)
- `workmotion` re-routed from personio (404) to workable (17 active jobs)

**Outcomes.**

- DB grew from 4786 to 6215 jobs (1429 net new across the day)
- Top 25 unchanged. Holidu Munich Team Lead Data Analytics at 90 still leads. The new SmartRecruiters jobs did not displace it because Continental's roles skew US/manufacturing or carry no JD content for stack scoring

**Discoveries.**

- SmartRecruiters returns 200 for stub accounts with zero active jobs, same pattern as Workable. Of 17 DACH enterprise candidates probed, only Continental and Visa had active boards. Bosch, Henkel, Allianz and others returned 0 and likely use slug variants
- Several Personio TARGETS had migrated off the platform between Day 3 and Day 4 runs. The probe-and-confirm pattern (one curl per ATS endpoint) is the cheapest way to detect this. forto, enpal, and tier moved to custom careers pages and are deferred until a generic HTML scraper exists

**Deferred to Day 5 and beyond.**

- Per-job JD fetch for Workable and SmartRecruiters. Highest-leverage improvement now that JD-text is the binding constraint on score quality
- Variant hunt for SmartRecruiters stub companies (bosch-careers, henkel-group, allianz-careers)
- Workday adapter (requires SCRAPERS registry signature change)
- Custom-page adapters for forto, enpal, tier
- Status column CLI
- Embedding-based scoring as 7th dimension