#!/usr/bin/env python3
"""
collect-github.py — Search GitHub for MCP server repositories.
Uses targeted queries sliced by topic and language to stay under
GitHub's 1000-result-per-query cap without alphabet chunking.
Outputs raw JSON to data/raw/github-raw.json for dedup and merge.
"""

import json
import subprocess
import time
from datetime import datetime, timezone

# Each query returns up to 1000 results — slice by topic/language for coverage
SEARCH_QUERIES = [
    # By topic
    "topic:mcp-server",
    "topic:modelcontextprotocol",
    "topic:mcp",
    # By name + language slices
    "mcp-server in:name language:python",
    "mcp-server in:name language:typescript",
    "mcp-server in:name language:javascript",
    "mcp-server in:name language:go",
    "mcp-server in:name language:rust",
    "mcp-server in:name language:java",
    "mcp-server in:name language:csharp",
    "mcp-server in:name language:ruby",
    # By description + language slices
    "modelcontextprotocol in:description language:python",
    "modelcontextprotocol in:description language:typescript",
    "modelcontextprotocol in:description language:javascript",
    "modelcontextprotocol in:description language:go",
    # Org-specific (Anthropic official servers)
    "org:modelcontextprotocol",
    "org:anthropics mcp",
]

OUTPUT_FILE = "data/raw/github-raw.json"
MAX_RESULTS = 1000


def gh_search(query, limit=1000):
    """Run gh search repos and return parsed results."""
    cmd = [
        "gh", "search", "repos",
        query,
        "--limit", str(limit),
        "--json", "name,fullName,description,url,stargazersCount,updatedAt,license,language",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"  [{query}] error: {stderr[:100]}")
            return []

        data = json.loads(result.stdout)
        print(f"  [{query}] fetched {len(data)} repos")
        return data

    except subprocess.TimeoutExpired:
        print(f"  [{query}] timeout")
        return []
    except Exception as e:
        print(f"  [{query}] error: {e}")
        return []


def normalize(repo, query):
    license_info = repo.get("license")
    license_key = license_info.get("key", "unknown") if isinstance(license_info, dict) else "unknown"

    return {
        "name": repo.get("fullName", repo.get("name", "")),
        "url": repo.get("url", ""),
        "description": repo.get("description") or "",
        "github_stars": repo.get("stargazersCount"),
        "last_updated": repo.get("updatedAt", "")[:10] if repo.get("updatedAt") else None,
        "license": license_key,
        "tags": [repo.get("language")] if repo.get("language") else [],
        "source": "github",
        "search_query": query,
    }


def main():
    import os
    os.makedirs("data/raw", exist_ok=True)

    seen = set()
    all_results = []

    for query in SEARCH_QUERIES:
        print(f"\nSearching GitHub for: {query}")
        raw = gh_search(query)
        for repo in raw:
            url = repo.get("url", "")
            if url and url not in seen:
                seen.add(url)
                all_results.append(normalize(repo, query))
        time.sleep(2)

    output = {
        "collected": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "github",
        "count": len(all_results),
        "entries": all_results,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone: {len(all_results)} unique repos written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
