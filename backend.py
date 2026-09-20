from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import requests
import concurrent.futures
import json
import os
import re
import time
from itertools import islice
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path
from threading import Condition, Lock, Thread, local
from uuid import uuid4

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Example for Oracle:
# CORS_ALLOWED_ORIGINS=https://oriolcot.github.io
# The default allows local development only.
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET"],
    allow_headers=[],
)

# Blizzard redirects the unlocalized endpoint. Going straight to en-us avoids
# the redirect and returns the current season in the top-level `seasonId` field.
BASE_URL = "https://hearthstone.blizzard.com/en-us/api/community/leaderboardsData"
APP_DIR = Path(__file__).resolve().parent
app.mount("/assets", StaticFiles(directory=APP_DIR / "assets"), name="assets")
ARCHIVE_DIR = APP_DIR / "archives"
SNAPSHOT_DIR = APP_DIR / "current_leaderboards"
SEASON_CACHE_SECONDS = 600
RESULT_CACHE_SECONDS = 600
CAREER_CACHE_SECONDS = int(os.getenv("CAREER_CACHE_SECONDS", "21600"))
MAX_CACHE_ENTRIES = 500
MAX_RATE_LIMIT_CLIENTS = 10000
MAX_RETAINED_CAREER_JOBS = 500
MAX_TAGS_PER_REQUEST = 20
MAX_PAGES_TO_SCAN = int(os.getenv("MAX_PAGES_TO_SCAN", "0"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
CAREER_JOB_TTL_SECONDS = int(os.getenv("CAREER_JOB_TTL_SECONDS", "3600"))
MAX_CONCURRENT_SEARCHES = int(os.getenv("MAX_CONCURRENT_SEARCHES", "2"))
SEARCH_QUEUE_WAIT_SECONDS = int(os.getenv("SEARCH_QUEUE_WAIT_SECONDS", "180"))
MAX_QUEUED_CAREER_JOBS = int(os.getenv("MAX_QUEUED_CAREER_JOBS", "4"))
TRUSTED_IPS = {
    ip.strip()
    for ip in os.getenv("TRUSTED_IPS", "").split(",")
    if ip.strip()
}
BTAG_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ0-9 _.'-]{2,32}(?:#[0-9]{1,8})?$")

# Capçaleres estàndard per evitar qualsevol bloqueig de xarxa
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

_lock = Lock()
_season_cache = {}
_result_cache = {}
_career_cache = {}
_request_times = defaultdict(list)
_career_jobs = {}
_archive_cache = {}
_snapshot_cache = {}
_live_hints = {}
_http_local = local()
_search_condition = Condition(Lock())
_search_queue = deque()
_active_searches = 0


class SearchQueueTimeout(Exception):
    """Raised when a search has waited too long for a shared upstream slot."""


def blizzard_get(params: dict, timeout: int = 10) -> dict:
    """Make a controlled request to Blizzard and validate the response."""
    if not hasattr(_http_local, "session"):
        _http_local.session = requests.Session()
        _http_local.session.headers.update(HEADERS)
    response = _http_local.session.get(BASE_URL, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "leaderboard" not in data:
        raise ValueError("Unexpected Blizzard response")
    return data


def get_client_ip(request: Request) -> str:
    """Use Nginx's forwarded client IP; the app only listens on loopback."""
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def archive_path(region: str, mode: str, season_id: int) -> Path:
    return ARCHIVE_DIR / region / mode / f"season-{season_id}.json"


def available_archived_seasons(region: str, mode: str) -> list[int]:
    directory = ARCHIVE_DIR / region / mode
    if not directory.exists():
        return []
    seasons = []
    for path in directory.glob("season-*.json"):
        try:
            seasons.append(int(path.stem.removeprefix("season-")))
        except ValueError:
            continue
    return sorted(seasons, reverse=True)


def load_archive_rows(region: str, mode: str, season_id: int):
    path = archive_path(region, mode, season_id)
    if not path.is_file():
        return None
    try:
        modified_at = path.stat().st_mtime_ns
        cache_key = str(path)
        with _lock:
            cached = _archive_cache.get(cache_key)
            if cached and cached["modified_at"] == modified_at:
                return cached["rows"]
        with path.open("r", encoding="utf-8") as archive_file:
            data = json.load(archive_file)
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid archive rows")
        with _lock:
            _archive_cache[cache_key] = {"modified_at": modified_at, "rows": rows}
        return rows
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def player_matches_tag(account_id: str, tag: str) -> bool:
    target = tag.lower()
    name_only = tag.split("#", 1)[0].lower()
    account_lower = account_id.lower()
    return account_lower == target or account_lower.startswith(name_only)


def find_player_in_rows(tag: str, rows: list, page: int = 0):
    for row in rows:
        account_id = str(row.get("accountid", ""))
        if player_matches_tag(account_id, tag):
            return {
                "btag": account_id,
                "rank": row.get("rank"),
                "rating": row.get("rating"),
                "page": page,
            }
    return None


def archived_player_results(tags: list[str], rows: list):
    results = []
    for tag in tags:
        player = find_player_in_rows(tag, rows)
        if player:
            results.append({"found": True, **player})
        else:
            results.append({"btag": tag, "found": False, "error": "Not found in this archived leaderboard"})
    return results


def acquire_search_slot():
    """Wait in FIFO order until one of the shared Blizzard search slots is free."""
    global _active_searches
    token = object()
    deadline = time.monotonic() + SEARCH_QUEUE_WAIT_SECONDS
    with _search_condition:
        _search_queue.append(token)
        while _search_queue[0] is not token or _active_searches >= MAX_CONCURRENT_SEARCHES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _search_queue.remove(token)
                _search_condition.notify_all()
                raise SearchQueueTimeout()
            _search_condition.wait(remaining)
        _search_queue.popleft()
        _active_searches += 1


def release_search_slot():
    """Always wake the next queued search after a completed or failed lookup."""
    global _active_searches
    with _search_condition:
        _active_searches = max(0, _active_searches - 1)
        _search_condition.notify_all()


def queued_search(function):
    """Apply the shared FIFO limit to a normal lobby lookup."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            acquire_search_slot()
        except SearchQueueTimeout as error:
            raise HTTPException(
                status_code=503,
                detail="The search queue is busy. Please try again in a moment.",
            ) from error
        try:
            return function(*args, **kwargs)
        finally:
            release_search_slot()
    return wrapper


def client_is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _lock:
        # Prune inactive clients and bound memory under high-cardinality traffic.
        if ip not in _request_times and len(_request_times) >= MAX_RATE_LIMIT_CLIENTS:
            stale = [key for key, times in _request_times.items()
                     if not times or now - times[-1] >= RATE_LIMIT_WINDOW_SECONDS]
            for key in stale:
                del _request_times[key]
            if len(_request_times) >= MAX_RATE_LIMIT_CLIENTS:
                return True
        recent = [t for t in _request_times[ip] if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= RATE_LIMIT_REQUESTS:
            _request_times[ip] = recent
            return True
        recent.append(now)
        _request_times[ip] = recent
        return False


def cached_result(key):
    now = time.monotonic()
    with _lock:
        item = _result_cache.get(key)
        if item and item["expires_at"] > now:
            return item["value"]
        if item:
            del _result_cache[key]
    return None


def store_result(key, value):
    now = time.monotonic()
    with _lock:
        if len(_result_cache) >= MAX_CACHE_ENTRIES:
            expired = [k for k, v in _result_cache.items() if v["expires_at"] <= now]
            for expired_key in expired:
                del _result_cache[expired_key]
            if len(_result_cache) >= MAX_CACHE_ENTRIES:
                _result_cache.pop(next(iter(_result_cache)))
        _result_cache[key] = {"value": value, "expires_at": now + RESULT_CACHE_SECONDS}


def cached_career_result(key):
    now = time.monotonic()
    with _lock:
        item = _career_cache.get(key)
        if item and item["expires_at"] > now:
            return item["value"]
        if item:
            del _career_cache[key]
    return None


def store_career_result(key, value):
    now = time.monotonic()
    with _lock:
        if len(_career_cache) >= MAX_CACHE_ENTRIES:
            expired = [k for k, v in _career_cache.items() if v["expires_at"] <= now]
            for expired_key in expired:
                del _career_cache[expired_key]
            if len(_career_cache) >= MAX_CACHE_ENTRIES:
                _career_cache.pop(next(iter(_career_cache)))
        _career_cache[key] = {"value": value, "expires_at": now + min(CAREER_CACHE_SECONDS, RESULT_CACHE_SECONDS)}

def get_current_season(region: str, mode: str) -> int:
    snapshot = load_current_snapshot(region, mode, None)
    if not snapshot:
        raise HTTPException(status_code=503, detail="Current leaderboard snapshot is unavailable. Please try again later.")
    return int(snapshot["season"])

def load_current_snapshot(region, mode, season):
    path = SNAPSHOT_DIR / f"{region}-{mode}.json"
    try:
        modified = path.stat().st_mtime_ns
        key = (region, mode)
        with _lock:
            cached = _snapshot_cache.get(key)
        if cached and cached[0] == modified:
            data = cached[1]
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("rows"), list):
                return None
            with _lock:
                _snapshot_cache[key] = (modified, data)
        if ((season is not None and data.get("season") != season) or data.get("region") != region
                or data.get("mode") != mode):
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def preferred_live_pages(tags, region, mode, season, total_pages):
    """Try saved rank neighborhoods, then scan the remainder from the bottom."""
    snapshot = load_current_snapshot(region, mode, season)
    hints = []
    for tag in tags:
        with _lock:
            known = _live_hints.get((region, mode, season, tag.lower()))
        if not known and snapshot:
            known = find_player_in_rows(tag, snapshot["rows"])
        if not known and not snapshot:
            for old_season in available_archived_seasons(region, mode):
                if old_season >= season:
                    continue
                known = find_player_in_rows(tag, load_archive_rows(region, mode, old_season) or [])
                if known:
                    break
        if known and isinstance(known.get("rank"), int):
            hints.append(max(1, min(total_pages, (known["rank"] - 1) // 25 + 1)))
    seen = {1}  # Page one was already fetched to obtain current pagination.
    for offset in (0, -1, 1, -2, 2):
        for center in hints:
            page = center + offset
            if 1 <= page <= total_pages and page not in seen:
                seen.add(page)
                yield page
    for page in range(total_pages, 1, -1):
        if page not in seen:
            yield page


def fetch_page(page: int, params: dict):
    try:
        data = blizzard_get({**params, "page": str(page)})
        if int(data["seasonId"]) != int(params["seasonId"]):
            raise ValueError("Season changed")
        return page, data["leaderboard"]["rows"]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return page, None


def find_live_players(tags, params):
    region, mode, season = params["region"], params["leaderboardId"], int(params["seasonId"])
    try:
        first = blizzard_get({**params, "page": "1"}, timeout=6)
        if int(first["seasonId"]) != season:
            raise ValueError("Season changed")
        board = first["leaderboard"]
        total_pages = int(board["pagination"]["totalPages"])
        first_rows = board["rows"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Blizzard did not return this season's leaderboard") from error
    found = {}
    pending = list(dict.fromkeys(tags))
    incomplete = False

    def consume(rows, page):
        for tag in list(pending):
            player = find_player_in_rows(tag, rows, page)
            if player:
                found[tag] = {"found": True, **player}
                pending.remove(tag)
                with _lock:
                    if len(_live_hints) >= MAX_CACHE_ENTRIES:
                        _live_hints.pop(next(iter(_live_hints)))
                    _live_hints[(region, mode, season, tag.lower())] = player

    consume(first_rows, 1)
    if pending and total_pages > 1:
        pages = preferred_live_pages(pending, region, mode, season, total_pages)
        if MAX_PAGES_TO_SCAN > 0:
            pages = islice(pages, max(0, MAX_PAGES_TO_SCAN - 1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            while pending:
                batch = list(islice(pages, MAX_WORKERS))
                if not batch:
                    break
                futures = [executor.submit(fetch_page, page, params) for page in batch]
                for future in futures:
                    page, rows = future.result()
                    if rows is None:
                        incomplete = True
                    else:
                        consume(rows, page)
    return [found.get(tag, {"btag": tag, "found": False,
             "incomplete": incomplete,
             "error": ("Some leaderboard pages were unavailable. Please retry."
                       if incomplete else "Not found in the current public leaderboard")}) for tag in tags]


def find_player_in_season(tag: str, params: dict):
    result = find_live_players([tag], params)[0]
    if result.get("incomplete"):
        raise RuntimeError("Some leaderboard pages were unavailable")
    return result if result["found"] else None

@app.get("/", response_class=HTMLResponse)
def serve_index():
    try:
        with (APP_DIR / "index.html").open("r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Unable to find index.html next to the application.</h1>"

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/seasons")
def seasons(mode: str = "battlegrounds", region: str = "US"):
    if mode not in {"battlegrounds", "battlegroundsduo"}:
        raise HTTPException(status_code=400, detail="Invalid game mode.")
    if region not in {"EU", "US", "AP"}:
        raise HTTPException(status_code=400, detail="Invalid region.")

    current_season = get_current_season(region, mode)
    # Closed seasons are listed only after they have been captured locally.
    # This avoids promising a historic lookup that would hit Blizzard live.
    all_seasons = sorted(
        set(available_archived_seasons(region, mode)) | {current_season},
        reverse=True,
    )
    return {
        "currentSeason": current_season,
        "seasons": all_seasons,
    }


@app.get("/buscar")
def search_players(
    request: Request,
    btags: str,
    mode: str = "battlegrounds",
    region: str = "US",
    season: str = "current",
):
    if mode not in {"battlegrounds", "battlegroundsduo"}:
        raise HTTPException(status_code=400, detail="Invalid game mode.")
    if region not in {"EU", "US", "AP"}:
        raise HTTPException(status_code=400, detail="Invalid region.")

    client_ip = get_client_ip(request)
    if client_ip not in TRUSTED_IPS and client_is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many searches. Please try again in a minute.")

    current_season = get_current_season(region, mode)
    if season == "current":
        season_id = current_season
    elif season.isdigit() and 1 <= int(season) <= current_season:
        season_id = int(season)
    else:
        raise HTTPException(status_code=400, detail="Invalid season.")
    tags_introduits = [t.strip() for t in btags.replace('\n', ',').split(',') if t.strip()]
    if not tags_introduits:
        raise HTTPException(status_code=400, detail="Enter at least one BattleTag.")
    if len(tags_introduits) > MAX_TAGS_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"A maximum of {MAX_TAGS_PER_REQUEST} BattleTags is allowed per search.")
    invalid_tags = [tag for tag in tags_introduits if not BTAG_PATTERN.fullmatch(tag)]
    if invalid_tags:
        raise HTTPException(status_code=400, detail="One or more BattleTags have an invalid format.")

    if season_id == current_season:
        snapshot = load_current_snapshot(region, mode, current_season)
        if not snapshot:
            raise HTTPException(status_code=503, detail="Current leaderboard snapshot is unavailable.")
        response = archived_player_results(tags_introduits, snapshot["rows"])
        for player in response:
            player["capturedAt"] = snapshot["capturedAt"]
            if not player.get("found"):
                player["error"] = "Not found in the latest leaderboard snapshot"
        return response

    cache_key = (tuple(sorted(tag.lower() for tag in tags_introduits)), mode, region, season_id)
    cached = cached_result(cache_key)
    if cached is not None:
        return cached

    # Every completed season is immutable and is served from the local archive.
    # Current-season searches return the timestamped local snapshot above.
    if season_id != current_season:
        rows = load_archive_rows(region, mode, season_id)
        if rows is None:
            raise HTTPException(
                status_code=404,
                detail="This completed season has not been archived yet.",
            )
        response = archived_player_results(tags_introduits, rows)
        store_result(cache_key, response)
        return response

    return search_live_players(tags_introduits, mode, region, season_id, cache_key)


@queued_search
def search_live_players(tags_introduits, mode, region, season_id, cache_key):
    """Verify current scores live, using local snapshots only as search hints."""
    try:
        response = find_live_players(tags_introduits, {
            "region": region, "leaderboardId": mode, "seasonId": str(season_id)})
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="Blizzard is unavailable right now. Please try again shortly.") from error
    if not any(player.get("incomplete") for player in response):
        store_result(cache_key, response)
    return response


def clean_up_career_jobs():
    now = time.monotonic()
    with _lock:
        stale_ids = [
            job_id
            for job_id, job in _career_jobs.items()
            if job.get("finished_at") and now - job["finished_at"] > CAREER_JOB_TTL_SECONDS
        ]
        for job_id in stale_ids:
            del _career_jobs[job_id]
        finished = sorted(
            ((job.get("finished_at", 0), key) for key, job in _career_jobs.items()
             if job["status"] in {"completed", "failed"})
        )
        for _, key in finished[:max(0, len(_career_jobs) - MAX_RETAINED_CAREER_JOBS + 1)]:
            del _career_jobs[key]


def run_career_search(job_id, tag, mode, region, current_season, seasons_to_scan, cache_key):
    """Publish local history before waiting for or scanning the live season."""
    started = time.monotonic()
    matches, unavailable, scanned = [], [], []

    def result():
        return {"btag": tag, "mode": mode, "region": region,
                "currentSeason": current_season, "capturedAt": (load_current_snapshot(region, mode, current_season) or {}).get("capturedAt"), "scannedSeasons": list(scanned),
                "unavailableSeasons": list(unavailable),
                "matches": sorted(matches, key=lambda match: match["season"], reverse=True),
                "elapsedSeconds": round(time.monotonic() - started, 1)}

    try:
        with _lock:
            _career_jobs[job_id]["status"] = "running"
        for season in seasons_to_scan:
            if season == current_season:
                continue
            rows = load_archive_rows(region, mode, season)
            if rows is None:
                unavailable.append(season)
            else:
                player = find_player_in_rows(tag, rows)
                if player:
                    matches.append({"season": season, **player})
            scanned.append(season)
        # The frontend can display these matches while live verification is queued.
        partial = result()
        with _lock:
            _career_jobs[job_id].update(status="queued", completed_seasons=len(scanned),
                                       current_season=current_season, result=partial)
        if current_season in seasons_to_scan:
            snapshot = load_current_snapshot(region, mode, current_season)
            if snapshot:
                player = find_player_in_rows(tag, snapshot["rows"])
                if player:
                    matches.append({"season": current_season, **player})
            else:
                unavailable.append(current_season)
            scanned.append(current_season)
        final = result()
        if not unavailable:
            store_career_result(cache_key, final)
        with _lock:
            _career_jobs[job_id].update(status="completed", completed_seasons=len(scanned),
                                       result=final, finished_at=time.monotonic())
    except Exception:
        with _lock:
            _career_jobs[job_id].update(status="failed", result=result(),
                detail="The season-history search stopped unexpectedly. Please try again later.",
                finished_at=time.monotonic())


@app.get("/career")
def start_career_search(
    request: Request,
    btag: str,
    mode: str = "battlegrounds",
    region: str = "US",
):
    """Start a protected all-season search for one player in one mode."""
    if mode not in {"battlegrounds", "battlegroundsduo"}:
        raise HTTPException(status_code=400, detail="Invalid game mode.")
    if region not in {"EU", "US", "AP"}:
        raise HTTPException(status_code=400, detail="Invalid region.")

    tag = btag.strip()
    if not tag or not BTAG_PATTERN.fullmatch(tag):
        raise HTTPException(status_code=400, detail="Enter one valid BattleTag.")

    client_ip = get_client_ip(request)
    if client_ip not in TRUSTED_IPS and client_is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many searches. Please try again in a minute.",
        )

    current_season = get_current_season(region, mode)
    seasons_to_scan = sorted(
        set(available_archived_seasons(region, mode)) | {current_season},
        reverse=True,
    )
    cache_key = (tag.lower(), mode, region, current_season,
                 (load_current_snapshot(region, mode, current_season) or {}).get("capturedAt"))
    cached = cached_career_result(cache_key)
    if cached is not None:
        return {"status": "completed", "result": cached}

    clean_up_career_jobs()
    job_id = uuid4().hex
    with _lock:
        queued_jobs = sum(
            job["status"] in {"queued", "running"}
            for job in _career_jobs.values()
        )
        if queued_jobs >= MAX_QUEUED_CAREER_JOBS:
            raise HTTPException(
                status_code=503,
                detail="The season-history queue is full. Please try again later.",
            )
        _career_jobs[job_id] = {
            "status": "queued",
            "completed_seasons": 0,
            "current_season": current_season,
            "total_seasons": len(seasons_to_scan),
        }
    try:
        Thread(
            target=run_career_search,
            args=(job_id, tag, mode, region, current_season, seasons_to_scan, cache_key),
            daemon=True,
        ).start()
    except Exception as error:
        with _lock:
            del _career_jobs[job_id]
        raise HTTPException(status_code=503, detail="Unable to start the season-history search.") from error

    return JSONResponse(
        status_code=202,
        content={
            "status": "queued",
            "jobId": job_id,
            "completedSeasons": 0,
            "currentSeason": current_season,
            "totalSeasons": len(seasons_to_scan),
        },
    )


@app.get("/career/{job_id}")
def career_search_status(job_id: str):
    with _lock:
        job = _career_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Season-history search not found or expired.")
        if job["status"] == "completed":
            return {"status": "completed", "result": job["result"]}
        if job["status"] == "failed":
            return {"status": "failed", "detail": job["detail"]}
        return {
            "status": job["status"],
            "completedSeasons": job["completed_seasons"],
            "currentSeason": job["current_season"],
            "totalSeasons": job["total_seasons"],
            "result": job.get("result"),
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
