# AgenticWatch.dev

DistroWatch-style directory of MCP (Model Context Protocol) servers.
Tracks 2,001+ servers ranked by GitHub stars, with categories, license info, transport type, and descriptions.

## What This Is

A plain static HTML site. No build step, no dependencies, no framework.
Cloudflare Pages serves `index.html` directly from the `main` branch of this repo.

Part of the **DirectoryBase** brand — DistroWatch-style directories for the agentic web.
Local path: `/Users/gregory/Developer/DirectoryBase/agenticwatch-site/`

## File Structure

```
agenticwatch-site/
├── index.html     — the entire site (DW1 DistroWatch design, standalone)
├── robots.txt     — explicitly welcomes all crawlers and AI agents
├── sitemap.xml    — single-URL sitemap for https://agenticwatch.dev/
└── README.md      — this file
```

## Design Reference

Source mockup (internal, not in this repo):
`/Users/gregory/Developer/Fortress/outputs/directory-mockups-review.html`

Winning design: **DW1 — AgenticWatch DistroWatch Style**

Design specs:
- Background: `#0D0D0F` | Accent: `#00C2FF` (cyan)
- Three-column layout: 180px left sidebar | flex center | 185px right sidebar
- Fonts: Space Grotesk (headings), JetBrains Mono (data/mono), 12px base
- All CSS is inline in `<style>` tags — no external stylesheets

## Infrastructure

- **Primary remote:** `http://192.168.7.70:30008/directorybase/agenticwatch-site.git` (Gitea on TrueNAS)
- **GitHub mirror:** `https://github.com/WolfNinja32/agenticwatch-site` (auto-syncs on every commit)
- **Deployment:** Cloudflare Pages → connected to GitHub → deploys `main` branch
- **Build:** None. Framework preset: None. Output directory: `/`

## How to Update Content

1. Edit `index.html` directly
2. `git add index.html && git commit -m "update: [what changed]"`
3. `git push` — Gitea push mirror syncs to GitHub automatically
4. Cloudflare Pages detects the GitHub push and deploys (typically under 60 seconds)

## Domain

`https://agenticwatch.dev` — DNS managed via Cloudflare. A/AAAA records point to Cloudflare Pages.

## Bus Test

A competent stranger can rebuild this from this README alone:
1. Clone the repo from Gitea or GitHub
2. Edit `index.html` with any text editor
3. Push to `main` — Cloudflare Pages handles the rest
4. No npm, no build tools, no config files needed
