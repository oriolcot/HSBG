# Host your own HSBG instance

This is generic deployment guidance. Private server addresses, credentials and production service files are intentionally not included.

## Choose the data mode

For a public community site, prefer **snapshot mode** so visitor searches do not multiply requests to Blizzard. Run `python refresh_current.py --scheduled` every five minutes in a scheduler using the project's working directory and virtual environment. Each invocation chooses one UTC time slot; the six boards repeat every 30 minutes. Failed or overlapping captures keep the preceding successful data.

For a personal instance, **live mode** is optional. It requires outbound HTTPS and DNS from the API process. A service sandbox that blocks outbound traffic must be deliberately adapted for your own deployment; changing the environment variable alone cannot override network restrictions. Keep the page and concurrency limits described in [Live mode](Live-mode.md).

## Serve the application

1. Install the repository and dependencies following [Local setup](Local-setup.md).
2. Create a dedicated unprivileged account for the web process.
3. Start `python -m uvicorn backend:app --host 127.0.0.1 --port 8000` through your process manager, with your chosen `HSBG_DATA_MODE` environment variable. Do not use `--reload` in production.
4. Place an HTTPS reverse proxy in front of it. Redirect HTTP to HTTPS and arrange certificate renewal.
5. Serve the HTML and API on the same origin. Do not expose port 8000 publicly.
6. Have the proxy overwrite `X-Real-IP` with the verified client IP. The API trusts this header for limits; never forward an untrusted client-provided value. If using a CDN, trust its client-IP header only from that CDN's published source ranges.
7. Apply request/resource limits, security headers, updates and backups appropriate to your host.

Keep code and archives read-only to the web account. A separate collector needs write permission only for `current_leaderboards/`. Protect credentials and personal files from both processes.

## Confirm the deployment

- `/health` returns `{"status":"ok"}`.
- `/seasons?region=EU&mode=battlegrounds` reports the intended `dataMode`.
- The homepage, logo and browser icons load over HTTPS.
- A search and a history lookup work; missing archives are understood.
- Snapshot mode needs no outbound Blizzard access from the API.
- HTTP redirects correctly and the API port is not internet-accessible.

The application loads JavaScript from `assets/app.js` and still uses inline styles. Test CSP in report-only mode before enforcing it. Restrict scripts to your own origin and the specific analytics host you use, without unsafe-inline or unsafe-eval. See [SECURITY.md](../../SECURITY.md).

## Publishing these guides to GitHub Wiki

A Wiki is a separate Git repository and is not updated by commits to the main project. Create its Home page in GitHub and paste the contents of [Home.md](Home.md). It links to the maintained guides in the main repository, so future documentation updates remain available without duplicating pages.
