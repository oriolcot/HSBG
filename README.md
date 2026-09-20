<p align="center">
  <a href="https://hsbg.win"><img src="assets/branding/bg-256.png" width="112" height="112" alt="HSBG logo"></a>
</p>

<h1 align="center">HSBG</h1>
<p align="center"><strong>Your climb. Across the seasons.</strong></p>
<p align="center">Battlegrounds ratings, regional rankings and season history.<br>Explore beyond the top 100.</p>
<p align="center"><a href="https://hsbg.win"><strong>Open HSBG ↗</strong></a> · <a href="#development">Development</a> · <a href="SECURITY.md">Security</a></p>

---

## Find your place in the tavern

Look up a player across available past seasons, or compare up to 20 player names in a selected leaderboard. **No account. No Battle.net login.**

| Find a player | Explore their history | Choose your leaderboard |
| --- | --- | --- |
| Public MMR and regional rank | Available archived seasons | Solo & Duos · Europe, Americas & Asia-Pacific |

Current results show the latest snapshot's capture time. Historical coverage generally starts above **8,000 MMR**; not every player or season is available.

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

<a id="development"></a>
<details>
<summary><strong>Development · local setup and tests</strong></summary>

## Project layout

- `backend.py`: FastAPI search API and same-origin frontend serving.
- `index.html`: responsive HSBG interface.
- `assets/branding/`: logo, browser icons and background textures.
- `archive_leaderboards.py`: resumable completed-season archive builder.
- `refresh_current.py`: current leaderboard snapshot collector.
- `tests/`: API behavior, resource-limit and history UI checks.
- `archives/` and `current_leaderboards/`: generated data, excluded from Git.

Private production configuration is intentionally excluded. See [SECURITY.md](SECURITY.md) for deployment guidance and responsible reporting.

## Run locally

Use **Python 3.11 or newer**.

```bash
git clone https://github.com/oriolcot/HSBG.git HSBG
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

Open [localhost:8000](http://127.0.0.1:8000). A fresh clone contains no leaderboard data. The interface loads, but searches need local snapshots or archives.

To capture the six current leaderboards (this contacts Blizzard and may take several minutes):

```bash
python refresh_current.py
```

The collector uses a Linux/POSIX file lock; on Windows, run it in WSL. `python refresh_current.py --scheduled` refreshes just the board assigned to the current UTC time slot. To refresh continuously, arrange for that command to run every five minutes using your own scheduler.

For historical data, review `python archive_leaderboards.py --help`. For example, build a single completed season with `--region EU --mode battlegrounds --start-season N --end-season N`, replacing `N` with the upstream season ID. These IDs may differ from Blizzard's publicly named season numbers. The default historical threshold is strictly above 8,000 MMR. Do not run multiple importers concurrently.

## Validation

```bash
python -m unittest discover -s tests -v
node tests/test_history_ui.cjs
```

Tests require no live Blizzard requests. Node.js is needed only for the frontend test.

## Security

HSBG does not ask for Battle.net credentials. Search inputs are validated and player results are rendered as text. Request limits help reduce abuse.

Private hosting configuration, credentials, operational logs and local data files are not part of the public source distribution. Security controls reduce risk but cannot guarantee that a service is vulnerability-free. Never enter passwords or access tokens into the player search.


</details>

## Analytics and support

The public site uses Cloudflare Web Analytics for usage and performance statistics.

Optional support: [Buy Me a Coffee](https://buymeacoffee.com/urycot). Donations are not required to search.

## Disclaimer

HSBG is not affiliated with or endorsed by Blizzard Entertainment. Hearthstone is a trademark or registered trademark of Blizzard Entertainment, Inc. Linked third-party services and their logos belong to their respective owners.
