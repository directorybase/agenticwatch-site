# AgenticWatch.dev Header System

This pack locks the website masthead around the final **sonar-minimal** mark.

## Included files

- `agenticwatch-header-desktop.svg` — primary desktop lockup
- `agenticwatch-header-mobile.svg` — mobile lockup with subtitle retained
- `agenticwatch-header-ultra-compact.svg` — narrow header or secondary placement
- `agenticwatch-header-dark-preview.svg` — presentation mockup on near-black
- `agenticwatch-wordmark-only.svg` — text-only fallback
- `agenticwatch-header.css` — responsive header CSS
- `agenticwatch-header-example.html` — multi-file Cloudflare Pages example
- `agenticwatch-header-inline-example.html` — single-file quick test version

## Recommended usage

### Desktop
Use `agenticwatch-header-desktop.svg` at about **520–760px** wide inside a constrained content container.

### Mobile
Switch to `agenticwatch-header-mobile.svg` below **720px** viewport width.

### Compact or utility placement
Use `agenticwatch-header-ultra-compact.svg` when the header area is tight or the subtitle feels too heavy.

## Color tokens

- Background: `#0D0D0F`
- Accent cyan: `#00C2FF`
- Primary text: `#EAFBFF`
- Secondary text: `#9FDBF0`
- Divider line: `#12303A`

## Typography

The SVG lockups are set up for a clean technical sans stack:

`Inter, Segoe UI, Helvetica, Arial, sans-serif`

## Practical note

For the live site, I would use:

1. `agenticwatch-final-sonar-minimal.svg` as the favicon/app symbol source
2. `agenticwatch-header-desktop.svg` for desktop header
3. `agenticwatch-header-mobile.svg` for mobile header
4. `agenticwatch-wordmark-only.svg` for places where the icon is already present separately
