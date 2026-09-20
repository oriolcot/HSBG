#!/usr/bin/env python3
"""Build a local, immutable archive of completed Battlegrounds leaderboards.

Run this only on the server. It intentionally works sequentially and skips an
archive that is already complete, so it can be stopped and resumed safely.
The current season is never written: the web app always reads that one live.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import requests


BASE_URL = "https://hearthstone.blizzard.com/en-us/api/community/leaderboardsData"
APP_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = APP_DIR / "archives"
REGIONS = ("EU", "US", "AP")
MODES = ("battlegrounds", "battlegroundsduo")
HEADERS = {
    "User-Agent": "HSMMR archive builder (community leaderboard lookup; contact: github.com/oriolcot/HSMMR)"
}


def get_json(params: dict, timeout: int, retries: int) -> dict:
    """Fetch one page with conservative backoff for temporary failures."""
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "leaderboard" not in data:
                raise ValueError("Unexpected leaderboard response")
            return data
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < retries - 1:
                wait_seconds = min(30, 2 ** attempt * 3)
                print(f"  temporary error; retrying in {wait_seconds}s ({error})", flush=True)
                time.sleep(wait_seconds)
    raise RuntimeError(f"Blizzard request failed after {retries} attempts: {last_error}")


def current_season(region: str, mode: str, timeout: int, retries: int) -> int:
    data = get_json({"region": region, "leaderboardId": mode, "page": "1"}, timeout, retries)
    try:
        return int(data["seasonId"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Response did not include a valid current season") from error


def compact_rows(rows: list) -> list[dict]:
    """Keep just the public fields the scanner needs, not the whole response."""
    return [
        {
            "rank": row.get("rank"),
            "accountid": row.get("accountid", ""),
            "rating": row.get("rating"),
        }
        for row in rows
        if isinstance(row, dict) and row.get("accountid")
    ]


def archive_season(region: str, mode: str, season: int, args: argparse.Namespace) -> bool:
    output = ARCHIVE_DIR / region / mode / f"season-{season}.json"
    if output.exists() and not args.overwrite:
        print(f"skip {region} {mode} season {season}: already archived", flush=True)
        return True

    params = {"region": region, "leaderboardId": mode, "seasonId": str(season)}
    first = get_json({**params, "page": "1"}, args.timeout, args.retries)
    leaderboard = first.get("leaderboard", {})
    total_pages = int(leaderboard.get("pagination", {}).get("totalPages", 0))
    if total_pages < 1:
        raise RuntimeError("Response did not include leaderboard pages")

    rows = compact_rows(leaderboard.get("rows", []))
    print(f"archive {region} {mode} season {season}: page 1/{total_pages}", flush=True)
    for page in range(2, total_pages + 1):
        time.sleep(args.delay)
        data = get_json({**params, "page": str(page)}, args.timeout, args.retries)
        rows.extend(compact_rows(data.get("leaderboard", {}).get("rows", [])))
        print(f"archive {region} {mode} season {season}: page {page}/{total_pages}", flush=True)

    document = {
        "season": season,
        "region": region,
        "mode": mode,
        "capturedAt": datetime.now(UTC).isoformat(),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, output)
    print(f"complete {region} {mode} season {season}: {len(rows)} players", flush=True)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create local archives for completed BG leaderboard seasons.")
    parser.add_argument("--region", choices=REGIONS, action="append", help="Archive only this region; repeat for several.")
    parser.add_argument("--mode", choices=MODES, action="append", help="Archive only this mode; repeat for several.")
    parser.add_argument("--start-season", type=int, default=1, help="First completed season to archive (default: 1).")
    parser.add_argument("--end-season", type=int, help="Last season to archive; default is the latest completed season.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between page requests (default: 1.0).")
    parser.add_argument("--timeout", type=int, default=15, help="Per-request timeout in seconds (default: 15).")
    parser.add_argument("--retries", type=int, default=3, help="Retries per failed page (default: 3).")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild archives that already exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.delay < 0.5:
        raise SystemExit("Use a delay of at least 0.5 seconds between requests.")
    if args.start_season < 1:
        raise SystemExit("--start-season must be 1 or higher.")

    regions = args.region or REGIONS
    modes = args.mode or MODES
    failures = []
    for region in regions:
        for mode in modes:
            try:
                live_season = current_season(region, mode, args.timeout, args.retries)
                last_completed = min(args.end_season or live_season - 1, live_season - 1)
                if last_completed < args.start_season:
                    print(f"nothing to archive for {region} {mode}", flush=True)
                    continue
                print(f"{region} {mode}: archiving seasons {args.start_season} to {last_completed} (live is {live_season})", flush=True)
                for season in range(args.start_season, last_completed + 1):
                    archive_season(region, mode, season, args)
                    time.sleep(args.delay)
            except Exception as error:
                failures.append(f"{region} {mode}: {error}")
                print(f"FAILED {region} {mode}: {error}", flush=True)

    if failures:
        raise SystemExit("Archive run finished with failures:\n" + "\n".join(failures))
    print("Archive run completed successfully.", flush=True)


if __name__ == "__main__":
    main()
