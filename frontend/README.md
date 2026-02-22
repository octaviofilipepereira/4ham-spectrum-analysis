<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# Frontend Skeleton

This is a lightweight HTML/CSS/JS prototype for the UI layout.
It expects the backend to serve `/api/*` endpoints and WebSocket streams.

## Run
- Serve the frontend directory with any static server.
- For development, run the backend and open index.html.

## Tests
- Run `node frontend/tests/presets.test.mjs` from repo root.

## Waterfall tooltip
- Hovering mode labels (FT8/CW/SSB) in the waterfall shows mode, frequency, callsign, last-seen time, and SNR.
- Callsign resolution order:
	1. nearest frequency match from recent callsign events
	2. fallback to the most recent detected callsign if no local match exists
- If the browser still shows stale behavior after updates, hard refresh with `Ctrl+Shift+R`.
