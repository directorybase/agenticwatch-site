#!/usr/bin/env python3
"""AgenticWatch Pipeline — Research, Copywriter, Card Assembly"""

import os
import json
import urllib.request
import datetime
import anthropic

LISTING_ID   = os.environ.get('LISTING_ID', '')
PRODUCT_NAME = os.environ.get('PRODUCT_NAME', '')
PRODUCT_URL  = os.environ.get('PRODUCT_URL', '')

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def fetch_product_content(url):
    content = ""

    if "github.com/" in url:
        parts = url.replace("https://github.com/", "").rstrip("/").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "AgenticWatch-Pipeline/1.0"
            }

            # Repo metadata
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    d = json.loads(resp.read())
                    content += f"Repo: {d.get('full_name', '')}\n"
                    content += f"Description: {d.get('description', '')}\n"
                    content += f"Stars: {d.get('stargazers_count', 0)}\n"
                    content += f"License: {(d.get('license') or {}).get('spdx_id', 'unknown')}\n"
                    content += f"Last pushed: {d.get('pushed_at', '')[:10]}\n"
                    content += f"Topics: {', '.join(d.get('topics', []))}\n\n"
            except Exception as e:
                print(f"Warning: repo metadata fetch failed: {e}")

            # README
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{owner}/{repo}/readme",
                    headers={**headers, "Accept": "application/vnd.github.raw"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    readme = resp.read().decode("utf-8", errors="replace")
                    content += "README:\n" + readme[:8000]
            except Exception as e:
                print(f"Warning: README fetch failed: {e}")

    return content


def research_agent(product_name, product_url, content):
    print("  Calling claude-sonnet-4-6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": f"""You are a research analyst for AgenticWatch, a directory of MCP servers and agentic tools.

Analyze this product and return a JSON object with these exact fields:
{{
  "summary": "2-3 sentence technical summary of what this tool does and why it matters to AI agents",
  "key_features": ["feature1", "feature2", "feature3"],
  "use_cases": ["use case 1", "use case 2"],
  "category": "one of: infrastructure, browser, filesystem, database, api, devtools, productivity, communication, other",
  "platforms": ["compatible platforms from: Claude, OpenAI, Cursor, Windsurf, Any"],
  "transport": "one of: stdio, sse, http, or null if unknown",
  "auth": "authentication method as a short string, or null if none",
  "difficulty": "one of: beginner, intermediate, advanced",
  "license": "SPDX identifier or unknown",
  "tags": ["relevant tech tags, max 5"],
  "github_stars": number or null,
  "last_updated": "YYYY-MM-DD or null"
}}

Product: {product_name}
URL: {product_url}

Content:
{content}

Return only valid JSON, no markdown fences, no other text."""}]
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def copywriter_agent(product_name, product_url, research):
    print("  Calling claude-sonnet-4-6...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": f"""You write directory listings for AgenticWatch, an authoritative directory of MCP servers and agentic tools.

Write a single description sentence for this listing.

Rules:
- Under 120 characters
- Lead with the capability, not the brand name
- No marketing words: powerful, revolutionary, seamless, robust, game-changing
- Written for developers and AI agents evaluating tools
- Plain statement of what it does and who it's for

Product: {product_name}
URL: {product_url}
Summary: {research["summary"]}
Category: {research["category"]}
Key features: {", ".join(research["key_features"])}

Return only the description text, no quotes, no other text."""}]
    )
    return response.content[0].text.strip()


def card_assembly(listing_id, product_name, product_url, research, description):
    return {
        "name": product_name,
        "url": product_url,
        "description": description,
        "category": research.get("category", "other"),
        "platforms": research.get("platforms", ["Claude"]),
        "transport": research.get("transport"),
        "auth": research.get("auth"),
        "difficulty": research.get("difficulty"),
        "github_stars": research.get("github_stars"),
        "last_updated": research.get("last_updated"),
        "license": research.get("license", "unknown"),
        "tags": research.get("tags", []),
        "featured": False,
        "_pipeline": {
            "listing_id": listing_id,
            "processed_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "pending_review"
        }
    }


def main():
    print(f"=== AgenticWatch Pipeline ===")
    print(f"Product:    {PRODUCT_NAME}")
    print(f"URL:        {PRODUCT_URL}")
    print(f"Listing ID: {LISTING_ID}")
    print()

    print("Step 1: Fetching product content...")
    content = fetch_product_content(PRODUCT_URL)
    print(f"  {len(content)} chars fetched")

    print("Step 2: Research Agent...")
    research = research_agent(PRODUCT_NAME, PRODUCT_URL, content)
    print(f"  Category:   {research.get('category')}")
    print(f"  Stars:      {research.get('github_stars')}")
    print(f"  Difficulty: {research.get('difficulty')}")
    print(f"  Transport:  {research.get('transport')}")

    print("Step 3: Copywriter Agent...")
    description = copywriter_agent(PRODUCT_NAME, PRODUCT_URL, research)
    print(f"  Description: {description}")

    print("Step 4: Card Assembly...")
    card = card_assembly(LISTING_ID, PRODUCT_NAME, PRODUCT_URL, research, description)

    # Append to pending-review.json
    pending_file = "data/pending-review.json"
    try:
        with open(pending_file) as f:
            pending = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pending = []

    # Deduplicate by listing_id
    pending = [e for e in pending if e.get("_pipeline", {}).get("listing_id") != LISTING_ID]
    pending.append(card)

    with open(pending_file, "w") as f:
        json.dump(pending, f, indent=2)

    print()
    print("=== Pipeline complete ===")
    print(f"Card written to {pending_file}")
    print()
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
