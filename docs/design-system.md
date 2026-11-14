# Design System — Sovereign AI Concierge

The source of truth for the web UI (`frontend/`).

**Theme: armoured-tech HUD** — red and gold "plating" over a dark gunmetal base,
with cyan for live readouts, a faint engineering grid and corner-bracket frames.
It is inspired by superhero tech suits in general: the UI uses **no character
names, logos, helmet imagery or other franchise trademarks**, and the emblem is a
generic glowing ring. Keep it that way if the theme evolves.

## Principles

1. **Clarity over theme.** The tech flavour lives in titles (Orbitron), colour,
   frames and the emblem. Every control, label and message uses plain words
   ("Budget for two", "Find restaurants", "Cost for two").
2. **Colour has one job each.**
   - **Red** — actions and selection (primary button, selected chips, focus of attention).
   - **Gold** — the #1 pick, ratings ≥ 4.0, titles, saved items, widened-search notices.
   - **Cyan** — live readouts (status, focus ring) and ratings 3.5–3.9.
   - Red is never used to mean "good" in data: weak ratings are muted red, strong ones gold.
3. **Facts first.** Cards lead with name, rating, area, type and price; the AI's
   reason and a real review follow; actions (Directions, Call, Zomato) close.
4. **Readable sizes.** Body text ≥ 14 px; secondary text ≥ 12 px. Long sentences
   (AI summary, reasons, reviews) use Space Grotesk, never the display font.
5. **Restrained motion.** Only the status dot pings; cards fade in once.

## Tokens (`frontend/style.css` → `:root`)

| Token | Value | Use |
|---|---|---|
| page background | `#09090B` + grid + red glow | `<body>` |
| `--brand-void` | `#050506` | Deepest background, scrollbar track |
| `--brand-armor` | `#0E0E11` | Inset areas: inputs, chip trays, review quotes |
| `--brand-plate` | `#141418` | Cards and panels |
| `--brand-surface` | `#1C1C22` | Controls, buttons, raised chips |
| `--brand-border` | `#3A3A44` | Default 1 px borders |
| `--brand-border-strong` | `#55555F` | Hover borders |
| `--brand-red` | `#EF4444` | Selection, accents, links |
| `--brand-red-deep` | `#DC2626` | Fills (primary button gradient `#E11D2E → #B91C1C`) |
| `--brand-gold` / `-light` | `#F59E0B` / `#FBBF24` | Top pick, high ratings, titles, frames |
| `--brand-cyan` | `#67E8F9` | Readouts, focus ring, mid ratings |
| `--brand-text` | `#F1F5F9` | Headings, primary text |
| `--brand-body` | `#CBD5E1` | Body text |
| `--brand-muted` | `#94A3B8` | Secondary text (meets AA on `#141418`) |

Ratings: ≥ 4.0 gold (`.rating-high`), 3.5–3.9 cyan (`.rating-mid`), < 3.5 muted
red (`.rating-low`), unrated "NEW" cyan (`.rating-new`).

## Typography

| Role | Font | Size |
|---|---|---|
| Brand / section titles (short) | Orbitron 600–800, tracked 0.08em (`font-display`) | 12–20 px |
| Restaurant names, summary, body | Space Grotesk 400–600 | 14–20 px |
| Readouts (status, ratings, latency) | JetBrains Mono | 12–13 px |

## Shape, frames & spacing

- Radius: cards `1rem`, controls `0.75rem`, chips/pills `0.4–0.5rem`.
- `.hud-frame` / `.rec-card`: gold corner brackets top-left and bottom-right;
  the top pick uses larger **red** brackets, a 2 px gold border and a faint red underglow.
- `.hud-title`: section title followed by a fading red rule.
- `.emblem`: round gold-rimmed badge with a red outer ring and cyan core glow.
- Spacing on an 8 px rhythm; card padding 20 px (24 px ≥ 640 px wide).

## Components (classes in `style.css`)

| Component | Class | Notes |
|---|---|---|
| Primary button | `.btn-primary` | Red gradient plating, gold edge |
| Result card | `.rec-card`, `.rec-card-top` | Icon tile (`.card-icon`) chosen from cuisine/type |
| Rating | `.rating-badge` + tone | Star icon + mono number |
| Tags | `.pill`, `.pill-feature` | Cuisines; features (Table booking, Pubs and bars…) |
| AI reason label | `.why-label` | Gold, uppercase, 12 px |
| Review | `.review-quote` | Italic, left rule, attributed "a Zomato reviewer" |
| Actions | `.action-btn`, `.save-btn.is-saved`, `.vote-btn` | Directions / Call / Zomato / Save / 👍👎 |
| Chips | `.cuisine-chip`, `.vibe-chip`, `.refine-chip`, `.step-chip` | Selection, examples, refine, relaxation steps |
| Segmented controls | `.budget-card`, `.rating-option`, `.toggle-chip` (+ `.active`) | Native radios/checkboxes, visually hidden |
| Readout text | `.hud-readout` | Cyan mono |

## Motion

Card fade-in (300 ms), skeleton shimmer while loading, status-dot ping. All are
disabled under `prefers-reduced-motion` (the grid background also stops being fixed).

## Assets

- `frontend/favicon.svg` — ring emblem (also served at `/favicon.ico`).
- `frontend/og-image.png` — 1200×630 link preview.
- Tailwind is precompiled to `frontend/tailwind.css` (`tools/tailwind`, `npm run build`).
