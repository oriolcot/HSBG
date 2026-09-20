from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import concurrent.futures
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock

app = FastAPI()

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
SEASON_CACHE_SECONDS = 600
RESULT_CACHE_SECONDS = 600
CAREER_CACHE_SECONDS = int(os.getenv("CAREER_CACHE_SECONDS", "21600"))
MAX_CACHE_ENTRIES = 500
MAX_TAGS_PER_REQUEST = 20
MAX_PAGES_TO_SCAN = int(os.getenv("MAX_PAGES_TO_SCAN", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "8"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
CAREER_RATE_LIMIT_REQUESTS = int(os.getenv("CAREER_RATE_LIMIT_REQUESTS", "1"))
CAREER_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("CAREER_RATE_LIMIT_WINDOW_SECONDS", "600"))
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
_career_request_times = defaultdict(list)
_career_scan_lock = Lock()


def blizzard_get(params: dict, timeout: int = 10) -> dict:
    """Make a controlled request to Blizzard and validate the response."""
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "leaderboard" not in data:
        raise ValueError("Unexpected Blizzard response")
    return data


def get_client_ip(request: Request) -> str:
    """Use Nginx's forwarded client IP; the app only listens on loopback."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def client_is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _lock:
        recent = [t for t in _request_times[ip] if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= RATE_LIMIT_REQUESTS:
            _request_times[ip] = recent
            return True
        recent.append(now)
        _request_times[ip] = recent
        return False


def client_is_career_rate_limited(ip: str) -> bool:
    """Limit expensive season-history searches separately from normal lookups."""
    now = time.monotonic()
    with _lock:
        recent = [t for t in _career_request_times[ip] if now - t < CAREER_RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= CAREER_RATE_LIMIT_REQUESTS:
            _career_request_times[ip] = recent
            return True
        recent.append(now)
        _career_request_times[ip] = recent
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
        _career_cache[key] = {"value": value, "expires_at": now + CAREER_CACHE_SECONDS}

def get_current_season(region: str, mode: str) -> int:
    """Fetch and cache the current season for the selected region and mode."""
    now = time.monotonic()
    cache_key = (region, mode)
    with _lock:
        cached = _season_cache.get(cache_key)
        if cached and cached["expires_at"] > now:
            return cached["value"]
    try:
        data = blizzard_get({'region': region, 'leaderboardId': mode}, timeout=5)
        season_id = int(data['seasonId'])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Blizzard is unavailable right now. Please try again shortly.")

    with _lock:
        _season_cache[cache_key] = {"value": season_id, "expires_at": now + SEASON_CACHE_SECONDS}
    return season_id

def fetch_page(page: int, params: dict):
    """Fetch one page without failing the full lookup on a network error."""
    p = params.copy()
    p['page'] = str(page)
    try:
        data = blizzard_get(p)
        return page, data.get('leaderboard', {}).get('rows', [])
    except (requests.RequestException, ValueError):
        return page, []


def find_player_in_season(tag: str, params: dict):
    """Find one BattleTag in one season without retaining any player data."""
    target = tag.lower()
    name_only = tag.split("#", 1)[0].lower()

    def match_row(rows, page):
        for row in rows:
            account_id = str(row.get("accountid", ""))
            account_lower = account_id.lower()
            if account_lower == target or account_lower.startswith(name_only):
                return {
                    "btag": account_id,
                    "rank": row.get("rank"),
                    "rating": row.get("rating"),
                    "page": page,
                }
        return None

    try:
        first_page = blizzard_get({**params, "page": "1"}, timeout=6)
        leaderboard = first_page.get("leaderboard", {})
        total_pages = leaderboard.get("pagination", {}).get("totalPages", 0)
        found = match_row(leaderboard.get("rows", []), 1)
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Blizzard did not return this season's leaderboard") from error

    if found or total_pages <= 1:
        return found

    pages_to_scan = min(total_pages, MAX_PAGES_TO_SCAN)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for page_start in range(2, pages_to_scan + 1, MAX_WORKERS):
            pages = range(page_start, min(page_start + MAX_WORKERS, pages_to_scan + 1))
            futures = [executor.submit(fetch_page, page, params) for page in pages]
            for future in concurrent.futures.as_completed(futures):
                page, rows = future.result()
                found = match_row(rows, page)
                if found:
                    return found
    return None

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
    oldest_season = max(1, current_season - 19)
    return {
        "currentSeason": current_season,
        "seasons": list(range(current_season, oldest_season - 1, -1)),
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
    if client_is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many searches. Please try again in a minute.")

    current_season = get_current_season(region, mode)
    if season == "current":
        season_id = current_season
    elif season.isdigit() and 1 <= int(season) <= current_season:
        season_id = int(season)
    else:
        raise HTTPException(status_code=400, detail="Invalid season.")
    params = {'region': region, 'leaderboardId': mode, 'seasonId': str(season_id)}
    
    tags_introduits = [t.strip() for t in btags.replace('\n', ',').split(',') if t.strip()]
    if not tags_introduits:
        raise HTTPException(status_code=400, detail="Enter at least one BattleTag.")
    if len(tags_introduits) > MAX_TAGS_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"A maximum of {MAX_TAGS_PER_REQUEST} BattleTags is allowed per search.")
    invalid_tags = [tag for tag in tags_introduits if not BTAG_PATTERN.fullmatch(tag)]
    if invalid_tags:
        raise HTTPException(status_code=400, detail="One or more BattleTags have an invalid format.")

    cache_key = (tuple(sorted(tag.lower() for tag in tags_introduits)), mode, region, season_id)
    cached = cached_result(cache_key)
    if cached is not None:
        return cached
    
    objectius = []
    for tag in tags_introduits:
        objectius.append({
            "original": tag,
            "lower": tag.lower(),
            "name_only": tag.split('#')[0].lower()
        })
        
    resultats = {obj["original"]: {"btag": obj["original"], "found": False, "error": "Not found (outside the scanned leaderboard)"} for obj in objectius}
    objectius_pendents = objectius.copy()

    try:
        data = blizzard_get({**params, 'page': '1'})
        total_pages = data.get('leaderboard', {}).get('pagination', {}).get('totalPages', 0)
        rows_p1 = data.get('leaderboard', {}).get('rows', [])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Blizzard is unavailable right now. Please try again shortly.")

    def check_players_on_page(rows, num_pag):
        nonlocal objectius_pendents
        trobat_algun = False
        for row in rows:
            acc_id = row.get('accountid', '')
            acc_id_lower = acc_id.lower()
            
            for obj in list(objectius_pendents):
                if acc_id_lower == obj["lower"] or acc_id_lower.startswith(obj["name_only"]):
                    resultats[obj["original"]] = {
                        "btag": acc_id,
                        "rank": row.get('rank'),
                        "rating": row.get('rating'),
                        "found": True,
                        "page": num_pag
                    }
                    objectius_pendents.remove(obj)
                    trobat_algun = True
        return trobat_algun

    check_players_on_page(rows_p1, 1)

    if not objectius_pendents or total_pages <= 1:
        response = list(resultats.values())
        store_result(cache_key, response)
        return response

    total_a_escanejar = min(total_pages, MAX_PAGES_TO_SCAN)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for page_start in range(2, total_a_escanejar + 1, MAX_WORKERS):
            pages = range(page_start, min(page_start + MAX_WORKERS, total_a_escanejar + 1))
            futures = [executor.submit(fetch_page, page, params) for page in pages]
            for future in concurrent.futures.as_completed(futures):
                num_pag, files_pag = future.result()
                if files_pag:
                    check_players_on_page(files_pag, num_pag)
            if not objectius_pendents:
                break
                        
    response = list(resultats.values())
    store_result(cache_key, response)
    return response


@app.get("/career")
def search_career(
    request: Request,
    btag: str,
    mode: str = "battlegrounds",
    region: str = "US",
):
    """Search every available season for one player in the selected mode only."""
    if mode not in {"battlegrounds", "battlegroundsduo"}:
        raise HTTPException(status_code=400, detail="Invalid game mode.")
    if region not in {"EU", "US", "AP"}:
        raise HTTPException(status_code=400, detail="Invalid region.")

    tag = btag.strip()
    if not tag or not BTAG_PATTERN.fullmatch(tag):
        raise HTTPException(status_code=400, detail="Enter one valid BattleTag.")
    if "," in tag or "\n" in tag:
        raise HTTPException(status_code=400, detail="Season history is available for one BattleTag at a time.")

    current_season = get_current_season(region, mode)
    seasons_to_scan = list(range(current_season, max(1, current_season - 19) - 1, -1))
    cache_key = (tag.lower(), mode, region, current_season)
    cached = cached_career_result(cache_key)
    if cached is not None:
        return cached

    client_ip = get_client_ip(request)
    if client_is_career_rate_limited(client_ip):
        minutes = max(1, CAREER_RATE_LIMIT_WINDOW_SECONDS // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Season-history search is limited to one every {minutes} minutes. Try again shortly.",
        )
    if not _career_scan_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="A season-history search is already running. Please try again shortly.",
        )

    started_at = time.monotonic()
    matches = []
    unavailable_seasons = []
    try:
        for season_id in seasons_to_scan:
            try:
                player = find_player_in_season(
                    tag,
                    {"region": region, "leaderboardId": mode, "seasonId": str(season_id)},
                )
            except RuntimeError:
                unavailable_seasons.append(season_id)
                continue
            if player:
                matches.append({"season": season_id, **player})
    finally:
        _career_scan_lock.release()

    response = {
        "btag": tag,
        "mode": mode,
        "region": region,
        "currentSeason": current_season,
        "scannedSeasons": seasons_to_scan,
        "unavailableSeasons": unavailable_seasons,
        "matches": matches,
        "elapsedSeconds": round(time.monotonic() - started_at, 1),
    }
    store_career_result(cache_key, response)
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
