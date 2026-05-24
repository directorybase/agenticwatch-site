#!/usr/bin/env python3
"""
refresh-stars.py — Refresh github_stars in data/mcp-servers.json from the
GitHub API, then commit + push to Gitea (which mirrors to GitHub).

Runs on dragonstone (daily cron). Replaces the retired update-stars.yml
workflow, whose data/stars.json output was force-wiped from GitHub every
30 min by the Gitea->GitHub push mirror and never reached a build. Writing
github_stars into mcp-servers.json from the Gitea side is mirror-safe.

The site reads star counts from mcp-servers.json (github_stars per entry),
so updating that file is what actually changes the displayed numbers.

Auth:
  GH_TOKEN   GitHub PAT (public-repo read) for the stargazers fetch  [required
             except for --self-test]

Error semantics (regression guard — do not weaken):
  * Confirmed 404            -> null the count (repo gone/renamed/private).
  * 403 / 429 (rate limit)   -> PRESERVE existing value; STOP fetching further.
  * network / timeout / 5xx  -> PRESERVE existing value; skip that one entry.
  Never overwrite a good count because of a transient error.

Conflict handling vs publish.py (the other writer of this file):
  fetch all stars FIRST, then `git pull --rebase`, then re-load the fresh
  file and apply — so star updates land on the latest entries even if
  publish.py committed during the ~10-min fetch window. Fail loudly on a
  non-fast-forward; never force.

Usage:
  python3 scripts/refresh-stars.py                # dry run: fetch + report, no write
  python3 scripts/refresh-stars.py --write         # write mcp-servers.json (no push)
  python3 scripts/refresh-stars.py --publish        # write + pull --rebase + commit + push
  python3 scripts/refresh-stars.py --self-test      # offline logic test (no network/token)
  python3 scripts/refresh-stars.py --limit 5        # cap fetches (smoke test)
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE_FILE = ROOT / "data" / "mcp-servers.json"

GITHUB_PREFIX = "https://github.com/"
API = "https://api.github.com/repos/"
SLEEP = 0.1
TIMEOUT = 15

# fetch result statuses
OK = "ok"               # got a count
GONE = "gone"           # confirmed 404 -> null it
SKIP = "skip"           # transient (network/5xx) -> preserve, continue
RATELIMIT = "ratelimit"  # 403/429 -> preserve, stop


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug_from_url(url):
    """Return 'owner/repo' for a GitHub URL, else None."""
    if not url or not url.startswith(GITHUB_PREFIX):
        return None
    parts = url[len(GITHUB_PREFIX):].rstrip("/").split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{owner}/{repo}"


def fetch_stars(slug, token):
    """Return (status, count). count is None unless status == OK."""
    req = urllib.request.Request(API + slug, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AgenticWatch-StarRefresh/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
            return OK, data.get("stargazers_count")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return GONE, None
        if e.code in (403, 429):
            return RATELIMIT, None
        return SKIP, None  # 5xx and anything else: treat as transient
    except Exception:
        return SKIP, None  # network/timeout/parse: transient


def ordered_unique_slugs(entries):
    """Unique 'owner/repo' slugs in first-seen order (dedupes repeat repos)."""
    seen, out = set(), []
    for e in entries:
        slug = slug_from_url(e.get("url", ""))
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def fetch_all(slugs, token, fetcher=fetch_stars, limit=None, log=print):
    """Fetch every slug. Returns (results map, stopped flag).
    Slugs absent from the map were never fetched (stopped/limited) and must
    be left untouched by apply_results."""
    results, stopped = {}, False
    for i, slug in enumerate(slugs):
        if limit is not None and i >= limit:
            break
        status, count = fetcher(slug, token)
        results[slug] = (status, count)
        if status == RATELIMIT:
            stopped = True
            log(f"  ! rate limited at {slug} ({i + 1}/{len(slugs)}); stopping, preserving the rest")
            break
        time.sleep(SLEEP)
    return results, stopped


def apply_results(data, results):
    """Mutate entries in place per the error semantics. Returns stats dict."""
    stats = {"updated": 0, "unchanged": 0, "gone": 0, "skipped": 0, "not_github": 0}
    for e in data["entries"]:
        slug = slug_from_url(e.get("url", ""))
        if slug is None:
            stats["not_github"] += 1
            continue
        if slug not in results:        # never fetched -> preserve
            stats["skipped"] += 1
            continue
        status, count = results[slug]
        if status == OK:
            if count != e.get("github_stars"):
                e["github_stars"] = count
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        elif status == GONE:
            if e.get("github_stars") is not None:
                e["github_stars"] = None
            stats["gone"] += 1
        else:                          # SKIP / RATELIMIT -> preserve existing
            stats["skipped"] += 1
    return stats


def write_file(data):
    data["stars_updated"] = utcnow_iso()
    with open(LIVE_FILE, "w") as f:
        json.dump(data, f, indent=2)   # match publish.py serialization


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def publish():
    """pull --rebase, stage, commit if changed, push. Fail loudly on non-FF."""
    git("pull", "--rebase")
    git("add", "data/mcp-servers.json")
    if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=ROOT).returncode == 0:
        print("No star changes — nothing to commit.")
        return
    git("commit", "-m", f"chore: refresh github_stars {utcnow_iso()}")
    git("push")


def run(mode, limit):
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is required (GitHub PAT, public-repo read). Aborting.")

    data = json.loads(LIVE_FILE.read_text())
    slugs = ordered_unique_slugs(data["entries"])
    print(f"Fetching stars for {len(slugs)} unique GitHub repos"
          + (f" (limit {limit})" if limit else "") + " ...")
    results, stopped = fetch_all(slugs, token, limit=limit)

    if mode == "publish":
        git("pull", "--rebase")                 # land on latest before applying
        data = json.loads(LIVE_FILE.read_text())  # re-load post-rebase

    stats = apply_results(data, results)
    print(f"  updated={stats['updated']} unchanged={stats['unchanged']} "
          f"gone={stats['gone']} skipped={stats['skipped']} "
          f"non-github={stats['not_github']}"
          + ("  [STOPPED early on rate limit]" if stopped else ""))

    if mode == "dry-run":
        print("Dry run — no file written. Use --write or --publish to persist.")
        return
    write_file(data)
    print(f"Wrote {LIVE_FILE}")
    if mode == "publish":
        # publish() re-stages the file we just wrote (already rebased above)
        git("add", "data/mcp-servers.json")
        if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=ROOT).returncode == 0:
            print("No star changes — nothing to commit.")
            return
        git("commit", "-m", f"chore: refresh github_stars {utcnow_iso()}")
        git("push")
        print("Pushed to Gitea.")


# ----------------------------- offline self-test -----------------------------

def self_test():
    failures = []

    def check(name, cond):
        print(("  PASS " if cond else "  FAIL ") + name)
        if not cond:
            failures.append(name)

    # slug parsing
    check("slug basic", slug_from_url("https://github.com/owner/repo") == "owner/repo")
    check("slug trailing slash", slug_from_url("https://github.com/owner/repo/") == "owner/repo")
    check("slug extra path", slug_from_url("https://github.com/owner/repo/tree/main") == "owner/repo")
    check("slug .git", slug_from_url("https://github.com/owner/repo.git") == "owner/repo")
    check("slug non-github", slug_from_url("https://glama.ai/blog/x") is None)
    check("slug owner-only", slug_from_url("https://github.com/owner") is None)
    check("slug empty", slug_from_url("") is None)

    # fetch_stars error mapping via a fake urlopen
    real_urlopen = urllib.request.urlopen

    class FakeResp:
        def __init__(self, payload):
            self._p = json.dumps(payload).encode()
        def read(self):
            return self._p
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def make_urlopen(behavior):
        def _u(req, timeout=None):
            if behavior == "ok":
                return FakeResp({"stargazers_count": 1234})
            if behavior == "404":
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            if behavior == "403":
                raise urllib.error.HTTPError(req.full_url, 403, "rate limited", {}, None)
            if behavior == "500":
                raise urllib.error.HTTPError(req.full_url, 500, "server error", {}, None)
            raise TimeoutError("boom")
        return _u

    try:
        urllib.request.urlopen = make_urlopen("ok")
        check("fetch 200 -> OK,count", fetch_stars("a/b", "t") == (OK, 1234))
        urllib.request.urlopen = make_urlopen("404")
        check("fetch 404 -> GONE", fetch_stars("a/b", "t") == (GONE, None))
        urllib.request.urlopen = make_urlopen("403")
        check("fetch 403 -> RATELIMIT", fetch_stars("a/b", "t") == (RATELIMIT, None))
        urllib.request.urlopen = make_urlopen("500")
        check("fetch 500 -> SKIP", fetch_stars("a/b", "t") == (SKIP, None))
        urllib.request.urlopen = make_urlopen("timeout")
        check("fetch timeout -> SKIP", fetch_stars("a/b", "t") == (SKIP, None))
    finally:
        urllib.request.urlopen = real_urlopen

    # apply_results semantics — the core regression guard
    data = {"entries": [
        {"url": "https://github.com/o/up", "github_stars": 10},     # OK changed
        {"url": "https://github.com/o/same", "github_stars": 50},    # OK same
        {"url": "https://github.com/o/gone", "github_stars": 99},    # 404 -> null
        {"url": "https://github.com/o/flaky", "github_stars": 77},   # SKIP -> preserve
        {"url": "https://github.com/o/notfetched", "github_stars": 5},  # absent -> preserve
        {"url": "https://glama.ai/blog/x", "github_stars": None},     # non-github
    ]}
    results = {
        "o/up": (OK, 20),
        "o/same": (OK, 50),
        "o/gone": (GONE, None),
        "o/flaky": (SKIP, None),
        # o/notfetched intentionally absent (simulates stop-before-reach)
    }
    stats = apply_results(data, results)
    e = data["entries"]
    check("apply: OK changed updates", e[0]["github_stars"] == 20)
    check("apply: OK same unchanged", e[1]["github_stars"] == 50)
    check("apply: 404 nulls", e[2]["github_stars"] is None)
    check("apply: SKIP preserves", e[3]["github_stars"] == 77)
    check("apply: not-fetched preserves", e[4]["github_stars"] == 5)
    check("apply: non-github untouched", e[5]["github_stars"] is None)
    check("apply: stats", stats == {"updated": 1, "unchanged": 1, "gone": 1,
                                    "skipped": 2, "not_github": 1})

    # fetch_all stops on rate limit and preserves the rest (absent from map)
    seq = iter([(OK, 1), (RATELIMIT, None), (OK, 3)])
    res, stopped = fetch_all(["a/1", "a/2", "a/3"], "t",
                             fetcher=lambda s, t: next(seq), log=lambda *_: None)
    check("fetch_all stops on ratelimit", stopped and "a/3" not in res)

    print(("\nSELF-TEST PASSED" if not failures else f"\nSELF-TEST FAILED: {failures}"))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="Refresh github_stars in mcp-servers.json")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="write the file (no push)")
    g.add_argument("--publish", action="store_true", help="write + pull --rebase + commit + push")
    g.add_argument("--self-test", action="store_true", help="offline logic test (no network/token)")
    ap.add_argument("--limit", type=int, default=None, help="cap number of fetches (smoke test)")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())
    mode = "publish" if args.publish else "write" if args.write else "dry-run"
    run(mode, args.limit)


if __name__ == "__main__":
    main()
