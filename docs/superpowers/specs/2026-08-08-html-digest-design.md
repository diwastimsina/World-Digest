# HTML digest output — design

Date: 2026-08-08. Status: approved in conversation.

## Goal

Give local runs a readable output. The script currently prints Telegram-markup
text or sends to Telegram; there is nothing pleasant to look at locally.

## Design

All changes in `main.py`:

1. `main()` collects structured section data (`name`, `emoji`, `synthesis`,
   `items`) instead of collapsing straight into Telegram strings.
2. Two renderers consume that data:
   - `format_telegram(sections, now)` — byte-identical behavior to today.
   - `render_html(sections, now)` — new, returns a self-contained newspaper-style
     page: serif masthead, date line, small-caps section headers, italic
     Gemini synthesis as an editor's note, headline list with muted sources.
     Inline CSS only, no webfonts, light + dark via `prefers-color-scheme`.
3. Each run with content overwrites `digest.html` in the project root and prints
   `Saved digest.html`. Quiet cycles leave the previous file in place.
4. HTML writing is wrapped in try/except so it can never break Telegram delivery.

## Out of scope

Archive/index of past digests; committing `digest.html` from GitHub Actions.

## Verification

Reset `seen.json`, run with `GEMINI_API_KEY`, open `digest.html`: all sections
render, synthesis italicized, links work, dark mode legible.
