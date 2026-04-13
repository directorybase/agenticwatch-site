#!/usr/bin/env python3
"""
collect-npm.py — Search npm registry for MCP server packages.
Outputs raw JSON to data/raw/npm-raw.json for dedup and merge.

Rate limit fallback: if a 429 is hit mid-search, automatically retries
the remaining results using alphabetical chunks (term + a*, term + b*, etc.)
"""

import json
import urllib.request
import urllib.parse
import time
import string
from datetime import datetime, timezone

SEARCH_TERMS = [
    "mcp-server",
    "@modelcontextprotocol",
    "model-context-protocol",
]

OUTPUT_FILE = "data/raw/npm-raw.json"
REGISTRY_URL = "https://registry.npmjs.org/-/v1/search"
RATE_LIMIT_DELAY = 10  # seconds to wait before switching to chunked mode


def fetch_page(query, from_offset, size=250):
    """Fetch one page. Returns (objects, total) or raises on error."""
    params = urllib.parse.urlencode({"text": query, "size": size, "from": from_offset})
    url = f"{REGISTRY_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AgenticWatch-Collector/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        return data.get("objects", []), data.get("total", 0)


def search_full(query):
    """Try to fetch all results for a query. Returns (results, hit_limit)."""
    results = []
    from_offset = 0

    while True:
        try:
            objects, total = fetch_page(query, from_offset)
            results.extend(objects)
            print(f"  [{query}] fetched {from_offset + len(objects)}/{total}")
            if from_offset + len(objects) >= total or not objects:
                return results, False
            from_offset += len(objects)
            time.sleep(0.3)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  [{query}] rate limited at offset {from_offset} — switching to chunked mode")
                return results, True
            else:
                print(f"  [{query}] HTTP {e.code} at offset {from_offset} — stopping")
                return results, False
        except Exception as e:
            print(f"  [{query}] error at offset {from_offset}: {e} — stopping")
            return results, False


def search_with_fallback(query, depth=0, max_depth=4):
    """
    Search query, recursively chunking a-z if rate limited.
    depth=0: "mcp-server"
    depth=1: "mcp-server a" ... "mcp-server z"
    depth=2: "mcp-server aa" ... "mcp-server az"
    etc. up to max_depth.
    """
    indent = "  " * (depth + 1)
    results, hit_limit = search_full(query)

    if hit_limit:
        if depth >= max_depth:
            print(f"{indent}Max depth reached for '{query}' — keeping partial results")
            return results

        print(f"{indent}Chunking '{query}' into a-z suffixes (depth {depth + 1})")
        for letter in string.ascii_lowercase:
            chunk_query = f"{query}{letter}"
            chunk_results = search_with_fallback(chunk_query, depth=depth + 1, max_depth=max_depth)
            results.extend(chunk_results)
            time.sleep(0.5)

    return results


def search_npm(query):
    """Search npm, recursively chunking on rate limit."""
    return search_with_fallback(query)


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

    for term in SEARCH_TERMS:
        print(f"\nSearching npm for: {term}")
        raw = search_npm(term)
        for pkg in raw:
            name = pkg.get("package", {}).get("name", "")
            if name and name not in seen:
                seen.add(name)
                all_results.append(normalize(pkg))
        time.sleep(2)

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
