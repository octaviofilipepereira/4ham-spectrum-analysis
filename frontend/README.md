<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-03-14 UTC
-->

# Frontend Skeleton

This is a lightweight HTML/CSS/JS prototype for the UI layout.
It expects the backend to serve `/api/*` endpoints and WebSocket streams.

## Run
- Serve the frontend directory with any static server.
- For development, run the backend and open index.html.

## Tests
- Run `node frontend/tests/presets.test.mjs` from repo root.

## Recent UI changes
- Session-based login now uses the backend `/api/auth/*` endpoints and an HTTP-only cookie session.
- Protected startup work is delayed until authentication succeeds, so the waterfall and WebSocket streams start cleanly after login.
- The scan toolbar now shows both the active scan range and the active CW decoder segment when CW mode is selected.

## Waterfall tooltip
- Hovering mode labels (FT8/CW/SSB) in the waterfall shows mode, frequency, callsign, last-seen time, and SNR.
- Callsign resolution order:
	1. nearest frequency match from recent callsign events
	2. fallback to the most recent detected callsign if no local match exists
- If the browser still shows stale behavior after updates, hard refresh with `Ctrl+Shift+R`.
