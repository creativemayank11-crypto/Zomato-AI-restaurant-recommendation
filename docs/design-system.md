# Design System — Sovereign AI Concierge

The source of truth for the web UI (`frontend/`). It supersedes the Google Stitch
export's `DESIGN.md` (zero-radius, chamfered "armour" style with a gold primary
button), which the built UI never followed. The decision recorded here: **rounded,
calm dark UI; emerald for actions; gold reserved for the top pick and titles.**

## Principles

1. **Clarity over theme.** The regal flavour lives in titles (Cinzel) and the gold
   accent. Every control, label and message uses plain words ("Budget for two",
   "Find restaurants", "Cost for two").
2. **One accent per job.** Emerald = interactive / selected / success. Gold = the
   #1 pick, section titles, saved items and warnings about widened searches.
   Nothing else glows; the only looping animation is the status dot.
3. **Facts first.** Cards lead with name, rating, area, type and price; the AI's
   reason and a real review follow; actions (Directions, Call, Zomato) close.
4. **Readable sizes.** Body text ≥ 14 px; secondary text ≥ 12 px. Long sentences
   (the AI summary, reasons, reviews) are always in Space Grotesk, never Cinzel.

## Tokens (`frontend/style.css` → `:root`)

| Token | Value | Use |
|---|---|---|
| `--brand-void` | `#070A0E` | Deepest background, scrollbar track |
| page background | `#0B0F14` | `<body>` |
| `--brand-armor` | `#0D131A` | Inset areas: inputs, chip trays, review quotes |
| `--brand-plate` | `#131B24` | Cards and panels |
| `--brand-surface` | `#182230` | Controls, buttons, raised chips |
| `--brand-border` | `#2E3E50` | Default 1 px borders |
| `--brand-border-strong` | `#3D5066` | Hover borders |
| `--brand-emerald` | `#10B981` | Focus ring, selected borders, links |
| `--brand-emerald-deep` | `#059669` | Primary button fill |
| `--brand-gold` / `-light` | `#F59E0B` / `#FBBF24` | Top pick, titles, saved, relaxation notices |
| `--brand-text` | `#F1F5F9` | Headings, primary text |
| `--brand-body` | `#CBD5E1` | Body text |
| `--brand-muted` | `#94A3B8` | Secondary text (meets AA on `#131B24`) |

Rating colours: ≥ 4.0 emerald (`.rating-high`), 3.5–3.9 amber (`.rating-mid`),
< 3.5 red (`.rating-low`), unrated "NEW" (`.rating-new`).

## Typography

| Role | Font | Size |
|---|---|---|
| Brand / section titles (short) | Cinzel 700, uppercase or small caps | 14–20 px |
| Restaurant names, summary, body | Space Grotesk 400–600 | 14–20 px |
| Numbers (ratings, latency, counts) | JetBrains Mono | 12–13 px |

## Shape & spacing

- Radius: cards `1rem`, controls `0.75rem`, chips/pills `0.4–0.5rem`.
- Borders: 1 px; the top pick uses a 2 px gold border.
- Spacing on an 8 px rhythm; card padding 20 px (24 px ≥ 640 px wide).
- No drop-shadow glows. Elevation is expressed with surface colour + border.

## Components (classes in `style.css`)

| Component | Class | Notes |
|---|---|---|
| Result card | `.rec-card`, `.rec-card-top` | Icon tile (`.card-icon`) chosen from cuisine/type |
| Rating | `.rating-badge` + tone | Star icon + mono number |
| Tags | `.pill`, `.pill-feature` | Cuisines; features (Table booking, Pubs and bars…) |
| AI reason label | `.why-label` | Gold, uppercase, 12 px |
| Review | `.review-quote` | Italic, left rule, attributed "a Zomato reviewer" |
| Actions | `.action-btn`, `.save-btn.is-saved`, `.vote-btn` | Directions / Call / Zomato / Save / 👍👎 |
| Chips | `.cuisine-chip`, `.vibe-chip`, `.refine-chip`, `.step-chip` | Selection, examples, refine, relaxation steps |
| Segmented controls | `.budget-card`, `.rating-option`, `.toggle-chip` (+ `.active`) | Native radios/checkboxes, visually hidden |

## Motion

Card fade-in (300 ms), skeleton shimmer while loading, status-dot ping. All are
disabled under `prefers-reduced-motion`.

## Assets

- `frontend/favicon.svg` — crown mark (also served at `/favicon.ico`).
- `frontend/og-image.png` — 1200×630 link preview.
- Tailwind is precompiled to `frontend/tailwind.css` (`tools/tailwind`, `npm run build`).
