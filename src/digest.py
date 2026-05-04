"""Render top-N unsent jobs to HTML and send via Resend.

Pipeline:
  1. select_top_jobs(only_unsent=True)   →  list of dicts with score + breakdown
  2. add jd_preview to each              →  plain text, truncated
  3. render Jinja template               →  one HTML string
  4. send via Resend                     →  email arrives
  5. update notified_at                  →  next run skips these jobs

Run from repo root:
  uv run python -m src.digest             # send for real
  uv run python -m src.digest --dry-run   # render to output/last_digest.html only
"""
# `from __future__ import annotations` makes all type hints lazy-evaluated strings.
# On Python 3.12 you don't strictly need it (PEP 604 `str | None` works natively),
# but keeping it is the modern convention — guarantees forward-compat and lets you
# reference types defined later in the file without quoting them.
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import resend
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.db import connect
from src.rank import select_top_jobs

# Project root — parent of src/ — used for templates/, .env, output/.
ROOT = Path(__file__).parent.parent

# Loads .env into os.environ. No-op if vars are already set in the shell, which
# is the right precedence (CI/cron-set vars beat local .env).
load_dotenv(ROOT / ".env")

# Tunables. Top-25 matches Day 2 plan; tighten later if inbox feels noisy.
TOP_N = 25
JD_PREVIEW_CHARS = 240


def _strip_html(html: str | None) -> str:
    """Drop tags and collapse whitespace. Duplicates score._strip_html intentionally —
    digest shouldn't reach into score's internals; private helpers stay private."""
    if not html:
        return ""
    # Some scrapers store JDs already entity-encoded — and a few are *double*
    # encoded (&amp;amp; → &amp; → &). Loop until unescape is a no-op so we
    # peel every layer. Cap at 3 passes to avoid pathological inputs.
    text = html
    for _ in range(3):
        new = unescape(text)
        if new == text:
            break
        text = new
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _make_preview(html: str | None, max_chars: int = JD_PREVIEW_CHARS) -> str:
    txt = _strip_html(html)
    if len(txt) <= max_chars:
        return txt
    # Cut at the last word boundary inside the limit so we don't slice mid-word.
    cut = txt[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"


def render_digest(jobs: list[dict]) -> str:
    """Pure function: jobs in → HTML out. No I/O, no env reads. Easy to unit-test."""
    env = Environment(
        # FileSystemLoader resolves template names against this dir. With it set,
        # {% extends "base.html" %} and {% include %} will Just Work later.
        loader=FileSystemLoader(ROOT / "templates"),
        # Autoescape every {{ var }} in .html/.htm templates. This is the XSS defense
        # for rendered job titles/companies/JD snippets that came from external sites.
        # Without it, a malicious JD could inject <script> into your inbox.
        autoescape=select_autoescape(["html", "htm"]),
        # trim_blocks: strip the newline after a {% block %} tag.
        # lstrip_blocks: strip leading whitespace before {% block %} tags.
        # Together they keep the rendered HTML clean — no blank-line vomit from
        # template indentation. Cosmetic but worth knowing.
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("digest.html")
    return template.render(
        jobs=jobs,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


def mark_notified(job_ids: list[str]) -> None:
    """Stamp notified_at = now() for the jobs we just emailed.
    Called only after a successful send so a Resend failure means we re-try next run."""
    if not job_ids:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as conn:
        # executemany binds (now, id) per row inside one transaction. The `with`
        # context manager commits on clean exit, rolls back on exception — atomic.
        conn.executemany(
            "UPDATE jobs SET notified_at = ? WHERE id = ?",
            [(now, jid) for jid in job_ids],
        )


def send_email(html: str, subject: str) -> dict:
    """Thin Resend wrapper. Returns the SDK response dict so the caller can log the id."""
    resend.api_key = os.environ["RESEND_API_KEY"]
    return resend.Emails.send({
        # onboarding@resend.dev is Resend's shared sandbox sender — works without a
        # verified domain but only sends to the email tied to your Resend account.
        # Once you verify a domain, swap to jobs@yourdomain.com.
        "from": "Job Pipeline <onboarding@resend.dev>",
        "to": [os.environ["DIGEST_EMAIL"]],
        "subject": subject,
        "html": html,
    })


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    # Fail-fast on missing env vars. Cheaper to crash here than after we've rendered
    # and the user has watched 0.5s of output go by wondering why nothing arrived.
    if not dry_run:
        for var in ("RESEND_API_KEY", "DIGEST_EMAIL"):
            if not os.environ.get(var):
                print(f"missing env var: {var}", file=sys.stderr)
                return 1

    jobs = select_top_jobs(limit=TOP_N, only_unsent=True)

    # Enrich with jd_preview here, not in the template. Keeps the template dumb —
    # all formatting / business decisions live in Python where they're testable.
    for j in jobs:
        j["jd_preview"] = _make_preview(j.get("jd_html"))

    html = render_digest(jobs)

    # Always write a local preview, even on real send. Costs one fs write, saves you
    # the "what did the last digest look like?" question during iteration.
    preview_path = ROOT / "output" / "last_digest.html"
    preview_path.parent.mkdir(exist_ok=True)
    preview_path.write_text(html, encoding="utf-8")
    print(f"rendered {len(jobs)} jobs → {preview_path}")

    if dry_run:
        print("dry run, not sending")
        return 0

    if not jobs:
        # No unsent jobs. Skip the email so the inbox doesn't fill with empties.
        # Flip this if you want a heartbeat confirming cron ran.
        print("nothing new to send")
        return 0

    subject = f"Job digest — {len(jobs)} new role{'s' if len(jobs) != 1 else ''}"
    resp = send_email(html, subject)
    print(f"sent: {resp}")

    mark_notified([j["id"] for j in jobs])
    print(f"marked {len(jobs)} jobs as notified")
    return 0


if __name__ == "__main__":
    # SystemExit(int) sets the process exit code. Matters when this runs under cron
    # or a CI runner that branches on non-zero.
    raise SystemExit(main())
