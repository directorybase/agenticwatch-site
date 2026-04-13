#!/usr/bin/env python3
"""
filter.py — AgenticWatch data pipeline, stage 2

Reads raw scraped data (github, npm, pypi), applies selection criteria,
deduplicates, and creates describe.job.json files in the agenticwatch-jobs
Gitea repo for the describe agent to process.

Usage:
  python3 scripts/filter.py                  # dry run — print candidates only
  python3 scripts/filter.py --submit         # create jobs in Gitea
  python3 scripts/filter.py --submit --limit 100  # cap batch size

Configure via environment variables:
  GITEA_URL     http://192.168.7.70:30008
  GITEA_TOKEN   Gitea API token
  GITEA_OWNER   gitea_admin
"""

import argparse
import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("filter")

ROOT        = Path(__file__).parent.parent
RAW_DIR     = ROOT / "data" / "raw"
LIVE_FILE   = ROOT / "data" / "mcp-servers.json"

GITEA_URL   = os.environ.get("GITEA_URL", "http://192.168.7.70:30008").rstrip("/")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
GITEA_OWNER = os.environ.get("GITEA_OWNER", "gitea_admin")
JOBS_REPO   = "agenticwatch-jobs"

GITEA_HEADERS = {
    "Authorization": f"token {GITEA_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "AgenticWatch-Filter/1.0",
}


# --------------------------------------------------------------------------- #
# Filter criteria
# --------------------------------------------------------------------------- #

# Names containing these strings are junk — demos, tutorials, personal projects
JUNK_NAME = re.compile(
    r"demo|example|tutorial|template|test|learning|intern|homework|"
    r"practice|course|workshop|hello|sample|starter|boilerplate|"
    r"sandbox|playground|poc|prototype|pipy|study|exercise|trial",
    re.I,
)

# Descriptions that are placeholder or too vague
JUNK_DESC = re.compile(
    r"^add your description|^todo|^tbd|^wip|^n/a|^placeholder|"
    r"^coming soon|^work in progress|^my first|^test",
    re.I,
)

# Descriptions that just restate the name (tautological)
# e.g. "MCP Server for Foo" when package is named foo-mcp-server
SUFFIX_STRIP = re.compile(
    r"[-_\s]*(mcp[-_\s]server|mcp[-_\s]tool|mcp[-_\s]client|"
    r"mcp[-_\s]service|[-_\s]mcp|[-_\s]server)$",
    re.I,
)


def is_tautological(name: str, desc: str) -> bool:
    """True if the description says nothing beyond the package name."""
    base = SUFFIX_STRIP.sub("", name).lower().replace("-", " ").replace("_", " ").strip()
    desc_lower = desc.lower().strip()
    # Strip common prefixes from description
    desc_clean = re.sub(r"^(mcp server for|an mcp server for|the mcp server for|"
                        r"mcp server (that|which)|official mcp server for)\s*", "", desc_lower)
    return desc_clean.strip(" .") == base


def passes_filters(name: str, desc: str) -> tuple[bool, str]:
    """Return (passes, reason_if_rejected)."""
    if not desc or len(desc.strip()) < 15:
        return False, "no_description"
    if JUNK_DESC.match(desc.strip()):
        return False, "placeholder"
    if JUNK_NAME.search(name):
        return False, "junk_name"
    if is_tautological(name, desc):
        return False, "tautological"
    return True, ""


# --------------------------------------------------------------------------- #
# Deduplication within batch
# --------------------------------------------------------------------------- #

def normalize_for_dedup(name: str) -> str:
    """Collapse variant package names to a common key."""
    n = name.lower()
    n = SUFFIX_STRIP.sub("", n)
    n = re.sub(r"[-_\s]+", "-", n).strip("-")
    return n


def pick_best(candidates: list[dict]) -> dict:
    """From a group of duplicates, pick the one with the most useful description."""
    def score(e):
        desc = e.get("description") or ""
        # Prefer longer, more specific descriptions
        # Penalise ones that just say "MCP server for X"
        words = len(desc.split())
        has_verbs = len(re.findall(
            r"\b(query|create|update|delete|search|monitor|execute|"
            r"control|automate|generate|fetch|list|manage|connect|"
            r"expose|integrate|read|write|run|invoke)\b",
            desc, re.I
        ))
        return words + (has_verbs * 3)
    return max(candidates, key=score)


def dedup_batch(entries: list[dict]) -> list[dict]:
    """Within the batch, keep one entry per normalized name."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        key = normalize_for_dedup(e["name"])
        groups.setdefault(key, []).append(e)

    result = []
    for key, group in groups.items():
        result.append(pick_best(group))
        if len(group) > 1:
            log.debug("Deduped %d variants of '%s'", len(group), key)
    return result


# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #

def load_live_urls() -> set[str]:
    with open(LIVE_FILE) as f:
        data = json.load(f)
    return {e.get("url", "").rstrip("/") for e in data.get("entries", [])}


def load_raw(source: str) -> list[dict]:
    path = RAW_DIR / f"{source}-raw.json"
    if not path.exists():
        log.warning("Raw file not found: %s", path)
        return []
    with open(path) as f:
        data = json.load(f)
    return data.get("entries", [])


def normalise_entry(e: dict, source: str) -> dict:
    """Normalise to a common shape regardless of source."""
    if source == "github":
        return {
            "name": e.get("name", ""),
            "url": e.get("url", "").rstrip("/"),
            "description": e.get("description") or "",
            "source": "github",
        }
    if source == "npm":
        raw_url = e.get("url", "")
        # Prefer GitHub URL if the npm url is a git remote
        if raw_url.startswith("git+https://github.com/"):
            url = raw_url[4:].rstrip("/")       # strip "git+"
            url = re.sub(r"\.git$", "", url)
        elif raw_url.startswith("git+"):
            url = f"https://www.npmjs.com/package/{e['name']}"
        else:
            url = raw_url.rstrip("/") or f"https://www.npmjs.com/package/{e['name']}"
        return {
            "name": e.get("name", ""),
            "url": url,
            "description": e.get("description") or "",
            "source": "npm",
        }
    if source == "pypi":
        return {
            "name": e.get("name", ""),
            "url": e.get("pypi_url", "").rstrip("/"),
            "description": e.get("description") or "",
            "source": "pypi",
        }
    return e


# --------------------------------------------------------------------------- #
# Gitea
# --------------------------------------------------------------------------- #

def gitea_file_exists(path: str) -> bool:
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{JOBS_REPO}/contents/{path}"
    req = urllib.request.Request(url, headers=GITEA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def gitea_create_file(path: str, content: dict, message: str) -> None:
    encoded = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
    payload = json.dumps({"message": message, "content": encoded}).encode()
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{JOBS_REPO}/contents/{path}"
    req = urllib.request.Request(url, data=payload, method="POST", headers=GITEA_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def get_existing_job_urls() -> set[str]:
    """Return URLs already queued in agenticwatch-jobs to avoid resubmitting."""
    try:
        url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{JOBS_REPO}/git/trees/main?recursive=true"
        req = urllib.request.Request(url, headers=GITEA_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = json.loads(resp.read())
    except Exception as e:
        log.warning("Could not fetch job tree: %s", e)
        return set()

    queued_urls = set()
    for item in tree.get("tree", []):
        if item["path"].endswith("/describe.job.json"):
            lid = item["path"].split("/")[1]
            try:
                raw_url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{JOBS_REPO}/raw/{item['path']}?ref=main"
                req = urllib.request.Request(raw_url, headers=GITEA_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    job = json.loads(resp.read())
                queued_urls.add(job.get("product_url", "").rstrip("/"))
            except Exception:
                pass
    return queued_urls


def submit_job(entry: dict) -> str:
    listing_id = str(uuid.uuid4())
    job = {
        "listing_id": listing_id,
        "job_type": "describe",
        "product_name": entry["name"],
        "product_url": entry["url"],
        "raw_description": entry["description"],
        "source": entry["source"],
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending",
        "retry_count": 0,
    }
    path = f"jobs/{listing_id}/describe.job.json"
    gitea_create_file(path, job, f"feat: queue describe job for {entry['name'][:40]}")
    return listing_id


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Filter raw MCP data into describe jobs")
    parser.add_argument("--submit", action="store_true",
                        help="Create jobs in Gitea (default: dry run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max jobs to submit (0 = no limit)")
    parser.add_argument("--source", choices=["github", "npm", "pypi"],
                        help="Process only one source")
    args = parser.parse_args()

    # Load live directory URLs
    live_urls = load_live_urls()
    log.info("Live directory: %d entries", len(live_urls))

    # Load existing job queue URLs (only relevant when submitting)
    queued_urls: set[str] = set()
    if args.submit:
        if not GITEA_TOKEN:
            log.error("GITEA_TOKEN not set — cannot submit jobs")
            return
        log.info("Fetching existing job queue...")
        queued_urls = get_existing_job_urls()
        log.info("Already queued: %d URLs", len(queued_urls))

    sources = [args.source] if args.source else ["github", "npm", "pypi"]

    all_candidates: list[dict] = []
    eliminated: dict[str, int] = {}

    for source in sources:
        raw = load_raw(source)
        log.info("Source %-6s — %d raw entries", source, len(raw))

        for e in raw:
            entry = normalise_entry(e, source)
            name = entry["name"]
            desc = entry["description"]
            url  = entry["url"]

            # Already in live directory
            if url in live_urls:
                eliminated["already_live"] = eliminated.get("already_live", 0) + 1
                continue

            # Already in job queue
            if url in queued_urls:
                eliminated["already_queued"] = eliminated.get("already_queued", 0) + 1
                continue

            passes, reason = passes_filters(name, desc)
            if not passes:
                eliminated[reason] = eliminated.get(reason, 0) + 1
                continue

            all_candidates.append(entry)

    log.info("Before dedup: %d candidates", len(all_candidates))
    candidates = dedup_batch(all_candidates)
    deduped = len(all_candidates) - len(candidates)
    log.info("After dedup:  %d candidates (%d collapsed)", len(candidates), deduped)

    log.info("Elimination breakdown:")
    for reason, count in sorted(eliminated.items(), key=lambda x: -x[1]):
        log.info("  %-20s %d", reason, count)

    if not args.submit:
        log.info("\nDRY RUN — first 30 candidates:")
        for e in candidates[:30]:
            log.info("  [%-6s] %s | %s", e["source"], e["name"], e["description"][:70])
        log.info("\nRe-run with --submit to create jobs in Gitea.")
        return

    # Submit
    limit = args.limit or len(candidates)
    batch = candidates[:limit]
    log.info("Submitting %d jobs to Gitea...", len(batch))

    submitted = 0
    failed = 0
    for entry in batch:
        try:
            lid = submit_job(entry)
            log.info("  + %s → %s", entry["name"][:40], lid[:8])
            submitted += 1
            time.sleep(0.3)  # stay well under Gitea rate limits
        except Exception as exc:
            log.error("  ! %s: %s", entry["name"][:40], exc)
            failed += 1

    log.info("Done: %d submitted, %d failed", submitted, failed)


if __name__ == "__main__":
    main()
