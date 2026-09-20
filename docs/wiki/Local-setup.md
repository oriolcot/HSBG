# Install HSBG locally

## Requirements

- Python 3.11 or newer and Git.
- An internet connection to install packages and query Blizzard in live mode.
- Linux/macOS, or Windows. The snapshot collector uses POSIX file locking: run that collector in WSL on Windows. The web API's live mode can run directly on Windows.

## Install

```bash
git clone https://github.com/oriolcot/HSBG.git
cd HSBG
python -m venv .venv
```

Activate the environment in the same terminal:

```bash
# Linux/macOS
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
python -m pip install -r requirements.txt
```

## First search without downloading snapshots

Linux/macOS:

```bash
HSBG_DATA_MODE=live uvicorn backend:app --host 127.0.0.1 --port 8000
```

Windows PowerShell:

```powershell
$env:HSBG_DATA_MODE = "live"
python -m uvicorn backend:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Select a mode and region, enter a public player name or BattleTag and search. The badge should read **On-demand lookup**. No API key, Battle.net account or background timer is required.

Use Ctrl+C to stop. Change environment variables before starting the process; restart after changes. `--reload` is optional for development, not public hosting.

## Use local snapshots instead

In a POSIX environment, with the virtual environment active:

```bash
python refresh_current.py
```

This captures all six current leaderboards and may take several minutes. Then start in the default mode:

```bash
HSBG_DATA_MODE=snapshot uvicorn backend:app --host 127.0.0.1 --port 8000
```

In PowerShell, set `$env:HSBG_DATA_MODE = "snapshot"` before launching Uvicorn. Without snapshots, current-season searches and season discovery return an unavailable-data error. The collector does not schedule itself: rerun it or configure a scheduler.

## Past seasons

Archives are not included in Git. Inspect the importer options:

```bash
python archive_leaderboards.py --help
```

To capture one completed season, replace `N` with its upstream season ID:

```bash
python archive_leaderboards.py --region EU --mode battlegrounds --start-season N --end-season N
```

The default threshold is strictly above 8,000 MMR. Upstream season IDs may differ from the season names Blizzard uses publicly. Only locally archived past seasons appear in the selector. Live mode does not automatically download old seasons.

## Troubleshooting

- **Current snapshot unavailable:** download snapshots, or explicitly select live mode and restart.
- **Blizzard unavailable / incomplete lookup:** retry later; upstream failures and scan limits must not be interpreted as proof of player absence.
- **No historical seasons:** build the relevant archives for that mode and region.
- **Import or package error:** activate the virtual environment, confirm Python 3.11+, and install requirements.
- **Too many searches:** wait a minute. Normal and history searches share a 10-search/minute/IP default.

[Live mode details](Live-mode.md) · [Hosting](Self-hosting.md)
