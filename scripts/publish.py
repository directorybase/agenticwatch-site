#!/usr/bin/env python3
"""
publish.py — AgenticWatch data pipeline, stage 5

Reads completed describe.result.json files from the agenticwatch-jobs Gitea repo,
appends new entries to mcp-servers.json, commits, and pushes.

Usage:
  python3 scripts/publish.py              # dry run — show what would be added
  python3 scripts/publish.py --publish    # write to mcp-servers.json + git push
  python3 scripts/publish.py --publish --limit 50

Configure via environment variables:
  GITEA_URL     http://192.168.7.70:30008
  GITEA_TOKEN   Gitea API token
  GITEA_OWNER   gitea_admin
"""

import argparse
import json
import logging
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("publish")

ROOT      = Path(__file__).parent.parent
LIVE_FILE   = ROOT / "data" / "mcp-servers.json"
RECENT_FILE = ROOT / "data" / "recent.json"
RECENT_MAX  = 50

GITEA_URL   = os.environ.get("GITEA_URL", "http://192.168.7.70:30008").rstrip("/")
GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "cffbb73974a0c0ae718c8e78d3d1d044a975412b")
GITEA_OWNER = os.environ.get("GITEA_OWNER", "gitea_admin")
JOBS_REPO   = "agenticwatch-jobs"

GITEA_HEADERS = {
    "Authorization": f"token {GITEA_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "AgenticWatch-Publish/1.0",
}


# --------------------------------------------------------------------------- #
# Gitea helpers
# --------------------------------------------------------------------------- #

def gitea_get(path: str) -> bytes:
    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{JOBS_REPO}/{path}"
    req = urllib.request.Request(url, headers=GITEA_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def fetch_tree() -> list[dict]:
    data = json.loads(gitea_get("git/trees/main?recursive=true"))
    return data.get("tree", [])


def fetch_file(path: str) -> dict:
    data = gitea_get(f"raw/{path}?ref=main")
    return json.loads(data)


# --------------------------------------------------------------------------- #
# Build a live-directory entry from a describe result
# --------------------------------------------------------------------------- #

SOURCE_TRANSPORT = {
    "pypi": "stdio",
    "npm":  "stdio",
    "github": None,
}


def build_entry(result: dict) -> dict:
    source = result.get("source", "github")
    return {
        "name":         result["product_name"],
        "url":          result["product_url"].rstrip("/"),
        "description":  result["description"],
        "category":     "other",
        "platforms":    ["Any"],
        "transport":    SOURCE_TRANSPORT.get(source),
        "auth":         None,
        "difficulty":   None,
        "github_stars": None,
        "last_updated": None,
        "license":      "unknown",
        "tags":         [],
        "featured":     False,
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Publish described MCP entries to live directory")
    parser.add_argument("--publish", action="store_true",
                        help="Write to mcp-servers.json and git push (default: dry run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max entries to publish per run (0 = no limit)")
    args = parser.parse_args()

    # Load live directory
    with open(LIVE_FILE) as f:
        live = json.load(f)
    live_urls = {e["url"].rstrip("/") for e in live["entries"]}
    log.info("Live directory: %d entries", len(live["entries"]))

    # Fetch all result files from Gitea
    log.info("Fetching job tree from Gitea...")
    tree = fetch_tree()
    result_paths = [item["path"] for item in tree if item["path"].endswith("describe.result.json")]
    log.info("Found %d describe.result.json files", len(result_paths))

    candidates = []
    skipped_dup = 0
    skipped_data = 0
    skipped_incomplete = 0

    for path in result_paths:
        try:
            result = fetch_file(path)
        except Exception as e:
            log.warning("Could not fetch %s: %s", path, e)
            continue

        if result.get("status") != "complete":
            skipped_incomplete += 1
            continue

        desc = result.get("description", "") or ""
        if not desc or "INSUFFICIENT_DATA" in desc or len(desc.strip()) < 20:
            skipped_data += 1
            continue

        url = result.get("product_url", "").rstrip("/")
        if url in live_urls:
            skipped_dup += 1
            continue

        candidates.append(result)

    log.info("Candidates: %d  (skipped: %d dup, %d insufficient, %d incomplete)",
             len(candidates), skipped_dup, skipped_data, skipped_incomplete)

    if not candidates:
        log.info("Nothing to publish.")
        return

    limit = args.limit or len(candidates)
    batch = candidates[:limit]

    if not args.publish:
        log.info("\nDRY RUN — would publish %d entries:", len(batch))
        for r in batch:
            log.info("  [%-6s] %s", r.get("source", "?"), r["product_name"])
            log.info("    %s", r["description"][:90])
        log.info("\nRe-run with --publish to write to mcp-servers.json.")
        return

    # Append entries
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries = [build_entry(r) for r in batch]
    for e in new_entries:
        e["added_at"] = now

    live["entries"].extend(new_entries)
    live["count"] = len(live["entries"])
    live["generated"] = now

    with open(LIVE_FILE, "w") as f:
        json.dump(live, f, indent=2)
        f.write("\n")

    log.info("Wrote %d new entries to mcp-servers.json (%d total)", len(new_entries), live["count"])

    # Update recent.json
    if RECENT_FILE.exists():
        with open(RECENT_FILE) as f:
            recent = json.load(f)
    else:
        recent = {"entries": []}

    recent_entries = new_entries + recent["entries"]
    recent_entries = recent_entries[:RECENT_MAX]
    recent_out = {
        "updated": now,
        "count": len(recent_entries),
        "description": "The most recently added MCP server entries. Updated automatically as new entries are published.",
        "entries": recent_entries,
    }
    with open(RECENT_FILE, "w") as f:
        json.dump(recent_out, f, indent=2)
        f.write("\n")

    log.info("Updated recent.json (%d entries)", len(recent_entries))

    # Git commit and push
    repo = ROOT
    try:
        subprocess.run(["git", "add", "data/mcp-servers.json", "data/recent.json"], cwd=repo, check=True)
        msg = f"publish: add {len(new_entries)} MCP entries from describe pipeline"
        subprocess.run(["git", "commit", "-m", msg], cwd=repo, check=True)
        subprocess.run(["git", "push"], cwd=repo, check=True)
        log.info("Pushed to Gitea — Cloudflare will pick up the update.")
    except subprocess.CalledProcessError as e:
        log.error("Git error: %s", e)
        log.error("Changes are written locally — push manually with: cd %s && git push", repo)


if __name__ == "__main__":
    main()
