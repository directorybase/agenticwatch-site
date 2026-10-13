#!/usr/bin/env python3
"""
collect-npm.py — Search npm registry for MCP server packages.
Outputs raw JSON to data/raw/npm-raw.json for dedup and merge.

npm's search API is a fuzzy relevance search across the whole registry, not
a substring filter -- a generic multi-word term like "mcp-server" or
"model-context-protocol" matches hundreds of thousands of loosely-related
packages (confirmed live: "mcp-server" -> total 404,845; "model-context-
protocol" -> total 281,252). The old alphabetical-chunking rate-limit
fallback assumed "total" meant "relevant results," and would have chunked
through that entire false population. Fixed by capping how deep into the
relevance-ranked results we look (npm's own scoring puts true matches at
the top) and filtering client-side for an actual "mcp" substring, the same
way collect-pypi.py already does.
"""

import json
import urllib.request
import urllib.parse
import time
from datetime import datetime, timezone

SEARCH_TERMS = [
    "mcp-server",
    "@modelcontextprotocol",
    "model-context-protocol",
]

OUTPUT_FILE = "data/raw/npm-raw.json"
REGISTRY_URL = "https://registry.npmjs.org/-/v1/search"
MAX_PAGES_PER_TERM = 3  # 3 x 250 = top 750 by relevance score, well past where true matches end
PAGE_SIZE = 250
RELEVANCE_FILTER_TERMS = ("mcp",)  # client-side substring check; drop anything that doesn't contain this


def fetch_page(query, from_offset, size=PAGE_SIZE):
    """Fetch one page. Returns (objects, total)."""
    params = urllib.parse.urlencode({"text": query, "size": size, "from": from_offset})
    url = f"{REGISTRY_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AgenticWatch-Collector/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        return data.get("objects", []), data.get("total", 0)


def search_npm(query):
    """Fetch up to MAX_PAGES_PER_TERM pages of npm's relevance-ranked results for query."""
    results = []
    from_offset = 0
    for page in range(MAX_PAGES_PER_TERM):
        try:
            objects, total = fetch_page(query, from_offset)
        except urllib.error.HTTPError as e:
            print(f"  [{query}] HTTP {e.code} at offset {from_offset} — stopping this term")
            break
        except Exception as e:
            print(f"  [{query}] error at offset {from_offset}: {e} — stopping this term")
            break
        if not objects:
            break
        results.extend(objects)
        print(f"  [{query}] fetched {from_offset + len(objects)} (registry reports {total:,} total matches — only the top {MAX_PAGES_PER_TERM * PAGE_SIZE} by relevance are considered)")
        if from_offset + len(objects) >= total:
            break
        from_offset += len(objects)
        time.sleep(0.3)
    return results


def is_relevant(pkg):
    p = pkg.get("package", {})
    haystack = f"{p.get('name', '')} {p.get('description', '')}".lower()
    return any(term in haystack for term in RELEVANCE_FILTER_TERMS)


def normalize(pkg):
    p = pkg.get("package", {})
    name = p.get("name", "")
    description = p.get("description", "")
    version = p.get("version", "")
    date = p.get("date", "")
    npm_url = f"https://www.npmjs.com/package/{name}"
    repo_url = p.get("links", {}).get("repository", "")

    return {
        "name": name,
        "url": repo_url if repo_url else npm_url,
        "npm_url": npm_url,
        "description": description,
        "version": version,
        "last_updated": date[:10] if date else None,
        "source": "npm",
    }


def main():
    import os
    os.makedirs("data/raw", exist_ok=True)

    seen = set()
    all_results = []
    dropped_irrelevant = 0

    for term in SEARCH_TERMS:
        print(f"\nSearching npm for: {term}")
        raw = search_npm(term)
        for pkg in raw:
            name = pkg.get("package", {}).get("name", "")
            if not name or name in seen:
                continue
            if not is_relevant(pkg):
                dropped_irrelevant += 1
                continue
            seen.add(name)
            all_results.append(normalize(pkg))
        time.sleep(2)

    print(f"\nDropped {dropped_irrelevant} relevance-ranked results that didn't contain 'mcp' in name/description.")

    output = {
        "collected": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "npm",
        "count": len(all_results),
        "entries": all_results,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone: {len(all_results)} unique packages written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
