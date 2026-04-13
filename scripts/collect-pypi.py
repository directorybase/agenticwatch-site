#!/usr/bin/env python3
"""
collect-pypi.py — Search PyPI for MCP server packages using the Simple API.
Outputs raw JSON to data/raw/pypi-raw.json for dedup and merge.

PyPI's search page is JS-gated, so we use the Simple API index to find
packages whose names match MCP-related keywords.
"""

import json
import urllib.request
import urllib.parse
import time
from datetime import datetime, timezone

KEYWORDS = [
    "mcp-server",
    "mcp_server",
    "mcp-",
    "modelcontextprotocol",
    "-mcp",
]

OUTPUT_FILE = "data/raw/pypi-raw.json"
SIMPLE_API_URL = "https://pypi.org/simple/"
PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"


def fetch_simple_index():
    """Fetch the full PyPI simple index (list of all package names)."""
    print("Fetching PyPI simple index (this may take a moment)...")
    req = urllib.request.Request(
        SIMPLE_API_URL,
        headers={
            "User-Agent": "AgenticWatch-Collector/1.0",
            "Accept": "application/vnd.pypi.simple.v1+json",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        packages = [p["name"] for p in data.get("projects", [])]
        print(f"  Index contains {len(packages):,} packages")
        return packages


def matches_keywords(name):
    name_lower = name.lower()
    return any(kw in name_lower for kw in KEYWORDS)


def fetch_package_details(name):
    """Fetch metadata for a single package from PyPI JSON API."""
    url = PYPI_JSON_URL.format(package=urllib.parse.quote(name))
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AgenticWatch-Collector/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            info = data.get("info", {})
            def clean(s):
                return "".join(c for c in (s or "") if c.isprintable())

            return {
                "name": clean(info.get("name", name)),
                "url": clean(info.get("project_url") or info.get("home_page") or f"https://pypi.org/project/{name}/"),
                "pypi_url": f"https://pypi.org/project/{name}/",
                "description": clean(info.get("summary", "")),
                "version": clean(info.get("version", "")),
                "license": clean(info.get("license", "unknown")),
                "last_updated": None,
                "source": "pypi",
            }
    except Exception:
        return None


def main():
    import os
    os.makedirs("data/raw", exist_ok=True)

    # Step 1: Get all package names from simple index
    all_packages = fetch_simple_index()

    # Step 2: Filter by keyword match
    candidates = [p for p in all_packages if matches_keywords(p)]
    print(f"  Matched {len(candidates)} candidate packages")

    # Step 3: Fetch details for each candidate
    results = []
    for i, name in enumerate(candidates):
        details = fetch_package_details(name)
        if details:
            results.append(details)
        if (i + 1) % 50 == 0:
            print(f"  Fetched details for {i + 1}/{len(candidates)}")
        time.sleep(0.1)  # Be gentle with PyPI

    output = {
        "collected": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "pypi",
        "count": len(results),
        "entries": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=True)

    print(f"\nDone: {len(results)} packages written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
