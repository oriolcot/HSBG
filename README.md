# HSBG · Battlegrounds rankings & season history

**[Open HSBG → hsbg.win](https://hsbg.win)**

HSBG is an independent community tool for looking up public Hearthstone Battlegrounds **MMR, regional rank and season history**, with coverage beyond the top 100.

Search one player across the available archived seasons, or compare up to 20 player names in a selected leaderboard. No account or Battle.net login is required.

## What you can explore

- **Solo and Duos**, across **Europe, Americas and Asia-Pacific**.
- A player's rating and position in the selected regional leaderboard.
- Available past seasons for the chosen mode and region.
- The latest saved current-season leaderboard, with its capture time.
- Links to community resources, trackers and other independent Battlegrounds tools.

## Data coverage and freshness

HSBG uses Blizzard's public leaderboard data. Public player names, ratings and ranks are stored on the server for searches.

Historical archives generally cover ratings **above 8,000 MMR**. Coverage depends on the season and the available public data; not every player or season is represented. A missing result does not prove that a player has never played or has no rating. Names without a BattleTag discriminator may be ambiguous.

On the production website, searches use local archives and snapshots: **a visitor's search does not trigger a Blizzard request**.

Current leaderboards are scheduled for refresh every 30 minutes, staggered as follows (UTC):

| Leaderboard | Minutes past each hour |
| --- | --- |
| Europe Solo | 00, 30 |
| Europe Duos | 05, 35 |
| Americas Solo | 10, 40 |
| Americas Duos | 15, 45 |
| Asia-Pacific Solo | 20, 50 |
| Asia-Pacific Duos | 25, 55 |

These are scheduled start times, not guarantees of freshness. A failed capture preserves the previous complete snapshot. Check the timestamp displayed with results.

The production search limit is **10 searches per minute per IP**, shared between regular and season-history searches.

## Source and deployment status

The live site has received updates that have not all been synchronized to this repository yet, including the tavern design and branding, snapshot-only searches and additional service isolation. This README describes the current production behavior; the checked-in code may still use the earlier live-search implementation and older defaults.

Server-side Nginx, Cloudflare and systemd configuration is also part of the deployment. Reading the frontend alone does not describe all deployed security controls.

## Run the checked-in application locally

Use **Python 3.11 or newer**.

```bash
git clone https://github.com/oriolcot/HSMMR.git HSBG
cd HSBG
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

Install dependencies and start the local server:

```bash
pip install -r requirements.txt
uvicorn backend:app --host 127.0.0.1 --port 8000 --reload
```

Open [localhost:8000](http://127.0.0.1:8000). Historical data files are not included in a fresh clone. Review the checked-in archive builder's options with `python archive_leaderboards.py --help` before downloading data. Avoid running multiple importers concurrently.

## Production architecture and security

The public website uses Cloudflare in front of Nginx. HTTP redirects to HTTPS; the origin also has a Let's Encrypt certificate. The frontend calls the API on the same origin.

Uvicorn listens only on loopback. The web service runs as a dedicated non-administrator user with read-only access to the necessary application files and leaderboard data. A separate collector can write only the current snapshots.

Additional deployed protections include validated search inputs, bounded caches and history jobs, request and resource limits, and browser security headers. Player results are rendered as text, rather than inserted as HTML.

The current Content Security Policy restricts framing, embedded objects and base URLs. It is **not yet a strict script policy**: the interface still contains inline JavaScript and CSS.

These controls reduce risk; they do not guarantee that the application, dependencies or hosting infrastructure are vulnerability-free. Never enter passwords, access tokens or other secrets into the player search.

## Analytics and support

The public site uses Cloudflare Web Analytics for usage and performance statistics.

Optional support: [Buy Me a Coffee](https://buymeacoffee.com/urycot). Donations are not required to search.

## Disclaimer

HSBG is not affiliated with or endorsed by Blizzard Entertainment. Hearthstone is a trademark or registered trademark of Blizzard Entertainment, Inc. Linked third-party services and their logos belong to their respective owners.
