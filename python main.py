## Deploy
- On Replit: create a new Repl, set the `.env` variables in Replit secrets, upload files, and run `python main.py`.
- Keep-alive: if you want uptime via UptimeRobot, add a small Flask keep-alive endpoint (optional).

## Notes
- Bot fetches candles directly from Deriv `ticks_history` endpoint via WebSocket (no trading executed).
- Signals are rate-limited: only sent when the signal changes for a symbol.
- Tweak thresholds in `.env` for more/less frequency.