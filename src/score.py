"""Rule-based job scoring tuned to a configured target profile.

Weighted linear rules, 0-100. Scoring is a pure function. No filters here.
Filters are applied at rank or display time so rules and filters can evolve independently.

Current configuration encodes a senior data leadership profile:
- Target roles: Head of Data, Analytics Lead, Principal, Staff, Director
- Location: Munich primary, DACH secondary, remote EU tertiary
- Stack: tiered against primary, secondary, and exposure tools
- Language: penalty for postings requiring business-fluent or native German
"""
from __future__ import annotations

import re


# -------- ROLE FIT (0–35) --------
# Phrases, not just keywords, to match leadership semantics.
# People-leadership titles. Primary target (Head of, Director, VP, Chief).
# These imply team ownership, hiring, C-level stakeholder work.
ROLE_LEAD_PEOPLE = [
    "head of data", "head of analytics", "head of ai", "head of engineering",
    "director of data", "director of analytics", "director data",
    "vp data", "vp analytics", "vp of data", "vp of analytics",
    "vp engineering", "vp of engineering",
    "data strategy", "chief data", "cdo", "chief analytics",
]

# Technical-leadership titles. Senior IC roles, usually no team management.
# Valid fallback bucket but not the primary target.
ROLE_LEAD_TECH = [
    "data lead", "analytics lead", "ai lead", "ml lead",
    "lead data", "lead analytics", "lead ai",
    "principal data", "principal analytics", "principal ai",
    "staff data", "staff analytics", "staff analytics engineer",
    "tech lead",
]
ROLE_SENIOR_DATA = [
    "senior data engineer", "senior analytics engineer",
    "senior data scientist", "senior data analyst",
    "senior analytics", "senior machine learning",
    "sr. data", "sr data",
    # Staff IC roles. Despite the "staff" prefix matching ROLE_LEAD_TECH,
    # these are senior individual contributor roles, not tech leadership.
    "staff data scientist", "staff data engineer", "staff data analyst",
    "staff machine learning",
]
ROLE_IC_DATA = [
    "data engineer", "analytics engineer", "data scientist",
    "data analyst", "machine learning engineer", "ml engineer",
]
ROLE_NEGATIVE = [
    "sales", "account executive", "business development", "recruiter",
    "marketing manager", "customer success", "partnerships",
    "installer", "installateur", "elektriker", "technician",
    "support", "customer service", "legal counsel", "finance manager",
]


# -------- SENIORITY (0–25) --------
SENIORITY_HIGH = [
    "principal", "staff", "head of", "director", "vp ", "vp of",
    "chief", "lead ",  # trailing space to avoid "leader" false positives are rare
]
SENIORITY_MID = ["senior ", "sr. ", "sr "]
# Hard filter (used elsewhere, not scored)
SENIORITY_KILL = [
    "junior", "jr.", "jr ", "intern", "working student", "werkstudent",
    "associate", "graduate", "entry-level", "entry level", "trainee",
    "apprentice", "praktikant",
]


# -------- TECH STACK (0–20, capped) --------
STACK_TOP = [  # +3 each, up to cap
    "dbt", "semantic layer", "text-to-sql", "text to sql",
    "microsoft fabric", "power bi", "tableau",
    "a/b test", "experimentation", "experiment",
    "governance", "gdpr", "data catalog",
    "stakeholder", "self-serve", "self serve",
    "redshift",
]
STACK_MID = [  # +2 each
    "python", " sql ", "airflow", "aws", "azure", "bigquery",
    "looker", "segment", "amplitude", "metabase", "sisense",
    "postgresql", "postgres", "mysql", "oracle",
    "etl", "elt", "data warehouse", "data mart", "dimensional",
]
STACK_LOW = [  # +1 each (secondary stack / table stakes / lower priority)
    "kafka", "spark", "pyspark", "dagster", "kubernetes", "k8s",
    "databricks", "snowflake", "n8n",
]


# -------- LOCATION (0–15) --------
LOC_PRIMARY = ["munich", "münchen", "muenchen"]
LOC_DACH = ["germany", "deutschland", "berlin", "hamburg", "frankfurt",
            "cologne", "köln", "stuttgart", "austria", "switzerland", "dach"]
LOC_REMOTE_EU = ["remote - eu", "remote eu", "remote emea", "remote europe",
                 "remote (eu)", "remote, eu", "emea"]
LOC_REMOTE_ANY = ["remote"]
# Non-EU locations: penalty, not just zero.
# These drop US/Asia jobs below Munich/EU even when role+seniority are strong.
# Full phrases safe for substring matching (can't be part of another word):
LOC_PENALTY_SUBSTRING = [
    "united states", "u.s.a", "san francisco", "new york", "los angeles",
    "seattle", "boston", "chicago", "austin", "denver", "atlanta",
    "portland", "philadelphia", "mountain view", "palo alto", "bellevue",
    "sunnyvale", "plano", "raleigh", "san jose",
    "california", "washington", "texas", "illinois", "massachusetts",
    "virginia", "colorado", "georgia", "florida", "pennsylvania",
    "north carolina", "oregon",
    "canada", "mexico", "brazil", "latin america",
    "japan", "india", "singapore", "china", "hong kong", "korea",
    "australia", "new zealand", "tokyo", "são paulo", "sao paulo",
]

# Short tokens that need word boundaries to avoid false positives
# (e.g. "us" matches "customer" as substring):
LOC_PENALTY_WORD = ["us", "usa", "u.s"]

# -------- LEADERSHIP CUES IN JD (0–5) --------
LEADERSHIP_CUES = [
    "lead a team", "lead the team", "manage a team", "manage the team",
    "team of ", "direct reports", "report to ceo", "report to cto",
    "report to cpo", "report to vp", "c-level", "executive",
    "grow the team", "hire", "mentoring", "coaching",
]


# -------- LANGUAGE PENALTY (0 to -10) --------
GERMAN_REQUIRED = [
    "fluent german", "fließend deutsch", "business german",
    "verhandlungssicher", "muttersprachlich",
    "native german", "german native", "c1 german", "c2 german",
    "deutsch auf muttersprachlichem",
]


# -------- HELPERS --------

def _hits(haystack: str, needles: list[str]) -> list[str]:
    """Case-insensitive substring matches. Returns the list of hits for debugging."""
    hay = haystack.lower()
    return [n for n in needles if n in hay]

def _word_hits(haystack: str, needles: list[str]) -> list[str]:
    """Word-boundary matches — prevents 'staff data' from matching 'staff database'.
    Used for role/seniority phrases where substring matches cause false positives."""
    hay = haystack.lower()
    matches = []
    for n in needles:
        # \b around the phrase. Phrases with spaces still work because \b also matches
        # at space boundaries within the phrase.
        if re.search(rf"\b{re.escape(n)}\b", hay):
            matches.append(n)
    return matches


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text)


# -------- DIMENSION SCORERS --------

def score_role(title: str) -> tuple[int, str]:
    t = title.lower()
    # People-leadership first. Primary target.
    hits = _word_hits(t, ROLE_LEAD_PEOPLE)
    if hits:
        return 40, f"people-lead role: {hits}"
    # Senior-IC patterns checked BEFORE tech-lead. Some senior-IC titles
    # (e.g. "Staff Data Scientist") match ROLE_LEAD_TECH via "staff data"
    # but are individual contributors, not leadership. More specific match wins.
    senior_hits = _word_hits(t, ROLE_SENIOR_DATA)
    if senior_hits:
        return 20, f"senior data role: {senior_hits}"
     # Technical lead / staff / principal IC. Fallback bucket.
    tech_hits = _word_hits(t, ROLE_LEAD_TECH)
    if tech_hits:
        return 30, f"tech-lead role: {tech_hits}"
    hits = _word_hits(t, ROLE_IC_DATA)
    if hits:
        base = 10
    else:
        base = 0
    neg = _hits(t, ROLE_NEGATIVE)
    if neg:
        return max(0, base - 25), f"IC data but NEGATIVE: {neg}"
    return base, f"IC data" if base else "no role match"


def score_seniority(title: str) -> tuple[int, str]:
    t = " " + title.lower() + " "  # pad so " senior " matches
    if _hits(t, SENIORITY_HIGH):
        return 25, f"high seniority: {_hits(t, SENIORITY_HIGH)}"
    if _hits(t, SENIORITY_MID):
        return 10, f"mid seniority: {_hits(t, SENIORITY_MID)}"
    return 0, "seniority unspecified"


def score_stack(jd: str | None) -> tuple[int, str]:
    plain = _strip_html(jd)
    if not plain:
        return 0, "no JD"
    top = _hits(plain, STACK_TOP)
    mid = _hits(plain, STACK_MID)
    low = _hits(plain, STACK_LOW)
    raw = len(top) * 3 + len(mid) * 2 + len(low) * 1
    pts = min(raw, 20)
    summary = f"top={len(top)} mid={len(mid)} low={len(low)} (raw={raw}, capped={pts})"
    return pts, summary


def score_location(loc: str | None) -> tuple[int, str]:
    """Location scoring. Note: penalty and match are NOT mutually exclusive
    for 'Remote - US' type postings — but since we check Munich/DACH/EU first,
    a penalty only applies when nothing else matched."""
    if not loc:
        return 0, "no location"
    loc_l = loc.lower()
    if _hits(loc_l, LOC_PRIMARY):
        return 15, f"MUNICH: {loc}"
    if _hits(loc_l, LOC_DACH):
        return 10, f"DACH: {loc}"
    if _hits(loc_l, LOC_REMOTE_EU):
        return 7, f"Remote EU: {loc}"
    # Penalty layer: if location explicitly names a non-EU region, drop below zero.
    # We check this BEFORE generic "remote" because "Remote - US" should penalize.
    # Split penalty into substring (safe phrases) and word-boundary (short tokens).
    # "US" as a substring would falsely match in "Customer Success" etc.
    penalty_hits = _hits(loc_l, LOC_PENALTY_SUBSTRING) + _word_hits(loc_l, LOC_PENALTY_WORD)
    if penalty_hits:
            return -25, f"NON-EU penalty: {loc}"
    if _hits(loc_l, LOC_REMOTE_ANY):
        return 3, f"generic remote: {loc}"
    return 0, f"other: {loc}"


def score_leadership(jd: str | None) -> tuple[int, str]:
    plain = _strip_html(jd)
    if not plain:
        return 0, "no JD"
    hits = _hits(plain, LEADERSHIP_CUES)
    if not hits:
        return 0, "no leadership cues"
    return min(len(hits), 5), f"leadership cues: {hits[:3]}..."


def score_language_penalty(jd: str | None) -> tuple[int, str]:
    plain = _strip_html(jd)
    if not plain:
        return 0, "no JD"
    hits = _hits(plain, GERMAN_REQUIRED)
    if hits:
        return -10, f"BUSINESS GERMAN REQUIRED: {hits}"
    return 0, "language ok"


# -------- IS IT A KILL? --------

def is_junior_kill(title: str) -> bool:
    """Used as a hard filter, not a score dimension.
    Rules and filters are separate concerns. Rules describe shape, filters
    describe policy. They evolve at different rates."""
    t = " " + title.lower() + " "
    return bool(_hits(t, SENIORITY_KILL))


# -------- MAIN SCORER --------

def score(job: dict) -> tuple[int, dict]:
    """Score one job row (sqlite Row converted to dict).
    Returns (total 0-100 clamped, reasons dict)."""
    title = job.get("title") or ""
    jd = job.get("jd_html") or ""
    loc = job.get("location") or ""

    r_pts, r_why = score_role(title)
    s_pts, s_why = score_seniority(title)
    t_pts, t_why = score_stack(jd)
    l_pts, l_why = score_location(loc)
    d_pts, d_why = score_leadership(jd)
    g_pts, g_why = score_language_penalty(jd)

    raw = r_pts + s_pts + t_pts + l_pts + d_pts + g_pts
    total = max(0, min(100, raw))

    return total, {
        "subtotals": {
            "role": r_pts, "seniority": s_pts, "stack": t_pts,
            "location": l_pts, "leadership": d_pts, "lang_penalty": g_pts,
        },
        "role": r_why,
        "seniority": s_why,
        "stack": t_why,
        "location": l_why,
        "leadership": d_why,
        "language": g_why,
    }