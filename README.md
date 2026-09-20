# BG Lobby Scanner

A small, open-source lookup tool for public Hearthstone Battlegrounds **MMR and regional leaderboard rank**. Paste a few BattleTags, choose Solo or Duos, a region, and a season to get a quick read on a lobby.

> MMR is the number. Leaderboard rank is the context: a player at #100 Europe and one at #500 Americas tell very different stories.

**Live site:** [mmrbg.duckdns.org](https://mmrbg.duckdns.org)

## What it does

- Looks up up to 20 BattleTags at once.
- Shows both a player's MMR and their position on the selected regional leaderboard.
- Supports Battlegrounds Solo and Battlegrounds Duos.
- Supports Europe, Americas, and Asia-Pacific.
- Lets players check Seasons 7 through the current leaderboard season, so ratings are read in the right context.
- Includes an optional one-player season-history search for the selected mode and region. Results are cached, rate-limited, and queued to protect the public service.
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
| `CAREER_CACHE_SECONDS` | `21600` | How long a completed season-history search is cached. |
| `CAREER_RATE_LIMIT_REQUESTS` | `1` | Season-history searches allowed per IP during its longer rate-limit window. |
| `CAREER_RATE_LIMIT_WINDOW_SECONDS` | `600` | Rate-limit window for the expensive season-history search. |
| `TRUSTED_IPS` | Empty | Comma-separated administrator IPs exempt from this app's rate limits. Set this only in the server environment, never in the repository. |
| `MAX_CONCURRENT_SEARCHES` | `2` | Total Blizzard-bound searches allowed at once across every visitor. |
| `SEARCH_QUEUE_WAIT_SECONDS` | `180` | Longest wait for a normal lookup before the service asks the visitor to retry. |

For a GitHub Pages front end, set:

```bash
CORS_ALLOWED_ORIGINS=https://oriolcot.github.io
```

## Deployment notes

The public instance runs behind Nginx, with Uvicorn listening only on `127.0.0.1:8000`. HTTPS is handled by Let's Encrypt. Keep the API server private and expose only the reverse proxy on ports 80 and 443. Season-history searches run in the background and report progress through short status requests, so they do not hold an Nginx request open while scanning.

## Support

The project may include an optional Buy Me a Coffee link to help cover hosting costs. It is never required to use the scanner.

## Disclaimer

This is an independent community project. It is not affiliated with or endorsed by Blizzard Entertainment. Hearthstone is a trademark or registered trademark of Blizzard Entertainment, Inc. in the U.S. and/or other countries. All third-party services linked from the site belong to their respective owners.
