# Changelog — AgenticWatch.dev

## v1.1 — 2026-04-02
- Internal detail pages — clicking a server name stays on agenticwatch.dev
- Hash-based routing: agenticwatch.dev/#/server/[slug]
- Detail page: metadata table, full description, difficulty dots, platform badges
- Detail sidebar: server stats + related entries in same category
- "View on GitHub →" CTA on detail page (intentional, not the first click)
- "More in [Category]" related entries panel
- Browser back button works correctly
- All rankings and sidebar links also go to internal detail pages
- Logo click returns to index

## v1.0-dev — 2026-04-02
- Fully working site: dynamic data load from data/mcp-servers.json
- Live search (name, description, category, tags)
- Category filter (sidebar + dropdown)
- Sort by stars / recent / A–Z
- Pagination (25 per page)
- All entry names and rankings link to canonical URLs (open in new tab)
- Stats and rankings calculated dynamically from real data
- Sidebars (Web top 5, Database top 5, Recently Added) populated from data

## v0.9 — 2026-04-02
- Initial design demo deployed to agenticwatch.dev
- DW1 DistroWatch-style layout (3-column: rankings / listings / stats)
- Static HTML — demo data only, not yet functional
- robots.txt with explicit AI crawler permissions
- sitemap.xml
- Gitea → GitHub mirror active, Cloudflare Pages deployment configured
