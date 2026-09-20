#!/usr/bin/env python3
"""Build a local, immutable archive of completed Battlegrounds leaderboards.

Run this only on the server. It uses bounded concurrency, checkpoints progress, and skips an
archive that is already complete, so it can be stopped and resumed safely.
The current season is never written: the web app always reads that one live.
"""

import argparse
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import requests


BASE_URL = "https://hearthstone.blizzard.com/en-us/api/community/leaderboardsData"
APP_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = APP_DIR / "archives"
REGIONS = ("EU", "US", "AP")
MODES = ("battlegrounds", "battlegroundsduo")
HEADERS = {
    "User-Agent": "HSBG archive builder (community leaderboard lookup; contact: github.com/oriolcot/HSBG)"
}


_local = threading.local()
_cooldown_lock = threading.Lock()
_cooldown_until = 0.0
_worker_limit = 3
_recent_errors = []


def record_error():
    """Reduce concurrency after five failed attempts within a rolling minute."""
    global _worker_limit, _cooldown_until
    now = time.monotonic()
    with _cooldown_lock:
        _recent_errors[:] = [stamp for stamp in _recent_errors if now - stamp < 60]
        _recent_errors.append(now)
        if len(_recent_errors) >= 5:
            _worker_limit = max(1, _worker_limit - 1)
            _cooldown_until = max(_cooldown_until, now + 30)
            _recent_errors.clear()
            print(f"  adaptive slowdown: 5 errors in 60s; concurrency {_worker_limit}; shared cooldown 30s", flush=True)


def batch_size(requested):
    with _cooldown_lock:
        return min(requested, _worker_limit)


def session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
        _local.session.headers.update(HEADERS)
    return _local.session


def wait_for_cooldown():
    while True:
        with _cooldown_lock:
            remaining = _cooldown_until - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(remaining)


def get_json(params: dict, timeout: int, retries: int) -> dict:
    """Fetch one page with conservative backoff for temporary failures."""
    global _cooldown_until
    last_error = None
    for attempt in range(retries):
        try:
            wait_for_cooldown()
            response = session().get(BASE_URL, params=params, timeout=timeout)
            if response.status_code in (429, 503):
                try:
                    cooldown = max(30.0, float(response.headers.get("Retry-After", "30")))
                except ValueError:
                    cooldown = 60.0
                with _cooldown_lock:
                    _cooldown_until = max(_cooldown_until, time.monotonic() + cooldown)
                print(f"  HTTP {response.status_code}; shared cooldown {cooldown:g}s", flush=True)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "leaderboard" not in data:
                raise ValueError("Unexpected leaderboard response")
            return data
        except (requests.RequestException, ValueError) as error:
            record_error()
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
        # Blizzard does not expose leaderboard pages for every historic season.
        # That is expected for the oldest seasons, not a reason to abandon the
        # remaining archive run.
        print(
            f"skip {region} {mode} season {season}: no public leaderboard data",
            flush=True,
        )
        return False

    checkpoint = output.with_suffix(".partial.json")
    rows = []
    next_page = 1
    if checkpoint.exists() and not args.overwrite:
        saved = json.loads(checkpoint.read_text())
        if (saved.get("minRating") == args.min_rating
                and saved.get("totalPages") == total_pages
                and saved.get("minRatingInclusive") is False):
            rows = saved["rows"]
            next_page = saved["nextPage"]
            print(f"resume {region} {mode} season {season}: page {next_page}", flush=True)

    def fetch_page(page):
        if page == 1:
            return first
        return get_json({**params, "page": str(page)}, args.timeout, args.retries)

    stopped = False
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        batch_start = next_page
        while batch_start <= total_pages:
            workers = batch_size(args.workers)
            futures = []
            for page in range(batch_start, min(batch_start + workers, total_pages + 1)):
                time.sleep(args.delay)
                futures.append((page, pool.submit(fetch_page, page)))
            for page, future in futures:
                leaderboard = future.result().get("leaderboard", {})
                page_rows = leaderboard.get("rows", [])
                if not page_rows:
                    raise ValueError(f"Unexpected empty leaderboard page {page}/{total_pages}")
                ratings = [float(row["rating"]) for row in page_rows]
                if any(not float("-inf") < rating < float("inf") for rating in ratings):
                    raise ValueError("Invalid leaderboard rating")
                rows.extend(compact_rows([
                    row for row, rating in zip(page_rows, ratings)
                    if rating > args.min_rating
                ]))
                print(f"archive {region} {mode} season {season}: page {page}/{total_pages}; MMR {max(ratings):g} to {min(ratings):g}; cutoff >{args.min_rating}", flush=True)
                if min(ratings) <= args.min_rating:
                    print(f"  reached {args.min_rating} MMR or lower; remaining pages skipped", flush=True)
                    stopped = True
                    break
            if stopped:
                break
            # Atomic checkpoint after an ordered batch; never expose partial archives.
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary_checkpoint = checkpoint.with_suffix(".tmp")
            temporary_checkpoint.write_text(json.dumps({
                "minRating": args.min_rating, "minRatingInclusive": False,
                "totalPages": total_pages, "nextPage": page + 1, "rows": rows,
            }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary_checkpoint, checkpoint)
            batch_start = page + 1

    document = {
        "season": season,
        "region": region,
        "mode": mode,
        "capturedAt": datetime.now(UTC).isoformat(),
        "minRating": args.min_rating,
        "minRatingInclusive": False,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, output)
    checkpoint.unlink(missing_ok=True)
    print(f"complete {region} {mode} season {season}: {len(rows)} players", flush=True)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create local archives for completed BG leaderboard seasons.")
    parser.add_argument("--region", choices=REGIONS, action="append", help="Archive only this region; repeat for several.")
    parser.add_argument("--mode", choices=MODES, action="append", help="Archive only this mode; repeat for several.")
    parser.add_argument("--start-season", type=int, default=1, help="First completed season to archive (default: 1).")
    parser.add_argument("--end-season", type=int, help="Last season to archive; default is the latest completed season.")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between page submissions (default: 0.25).")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent page requests, 1 to 4 (default: 3).")
    parser.add_argument("--timeout", type=int, default=15, help="Per-request timeout in seconds (default: 15).")
    parser.add_argument("--retries", type=int, default=3, help="Retries per failed page (default: 3).")
    parser.add_argument("--min-rating", type=int, default=8000, help="Archive only MMR strictly above this threshold (default: 8000).")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild archives that already exist.")
    return parser.parse_args()


def main() -> None:
    global _worker_limit
    args = parse_args()
    _worker_limit = args.workers
    if args.delay < 0.25:
        raise SystemExit("Use a delay of at least 0.25 seconds between requests.")
    if not 1 <= args.workers <= 4:
        raise SystemExit("--workers must be between 1 and 4.")
    if args.min_rating < 0:
        raise SystemExit("--min-rating must be 0 or higher.")
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
