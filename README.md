# BG Lobby Scanner

A small, open-source lookup tool for public Hearthstone Battlegrounds leaderboard ratings. Paste a few BattleTags, choose Solo or Duos, a region, and a season to get a quick read on a lobby.

**Live site:** [mmrbg.duckdns.org](https://mmrbg.duckdns.org)

## What it does

- Looks up up to 20 BattleTags at once.
- Supports Battlegrounds Solo and Battlegrounds Duos.
- Supports Europe, Americas, and Asia-Pacific.
- Lets players check the current or an earlier leaderboard season.
- Uses Blizzard's public leaderboard endpoint; it does not request a Battle.net login or store player data.

## Project layout

- `backend.py` — FastAPI service that retrieves and searches the public leaderboard.
- `index.html` — the responsive, single-page interface served by the API.
- `requirements.txt` — Python dependencies.

## Run locally

Requires Python 3.10 or newer.

```bash
git clone https://github.com/oriolcot/HSMMR.git
cd HSMMR
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source .venv/bin/activate
```

Install and start the app:

```bash
pip install -r requirements.txt
uvicorn backend:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Configuration

The service is safe to run with its defaults. These optional environment variables are useful for a deployment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CORS_ALLOWED_ORIGINS` | Localhost only | Comma-separated web origins allowed to call the API. |
| `MAX_PAGES_TO_SCAN` | `40` | Number of leaderboard pages checked for each lookup. |
| `MAX_WORKERS` | `8` | Maximum concurrent leaderboard requests. |
| `RATE_LIMIT_REQUESTS` | `8` | Requests allowed per IP during the rate-limit window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window in seconds. |

For a GitHub Pages front end, set:

```bash
CORS_ALLOWED_ORIGINS=https://oriolcot.github.io
```

## Deployment notes

The public instance runs behind Nginx, with Uvicorn listening only on `127.0.0.1:8000`. HTTPS is handled by Let's Encrypt. Keep the API server private and expose only the reverse proxy on ports 80 and 443.

## Support

The project may include an optional Buy Me a Coffee link to help cover hosting costs. It is never required to use the scanner.

## Disclaimer

This is an independent community project. It is not affiliated with or endorsed by Blizzard Entertainment. Hearthstone is a trademark or registered trademark of Blizzard Entertainment, Inc. in the U.S. and/or other countries. All third-party services linked from the site belong to their respective owners.
