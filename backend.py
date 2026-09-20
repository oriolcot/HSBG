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

# Defineix-los a Oracle, per exemple:
# CORS_ALLOWED_ORIGINS=https://oriolcot.github.io
# El valor per defecte només permet el desenvolupament local.
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

BASE_URL = "https://hearthstone.blizzard.com/api/community/leaderboardsData"
APP_DIR = Path(__file__).resolve().parent
SEASON_CACHE_SECONDS = 600
RESULT_CACHE_SECONDS = 600
MAX_CACHE_ENTRIES = 500
MAX_TAGS_PER_REQUEST = 20
MAX_PAGES_TO_SCAN = int(os.getenv("MAX_PAGES_TO_SCAN", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "8"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
BTAG_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ0-9 _.'-]{2,32}(?:#[0-9]{1,8})?$")

# Capçaleres estàndard per evitar qualsevol bloqueig de xarxa
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

_lock = Lock()
_season_cache = {"value": None, "expires_at": 0.0}
_result_cache = {}
_request_times = defaultdict(list)


def blizzard_get(params: dict, timeout: int = 10) -> dict:
    """Fa una petició controlada a Blizzard i valida la resposta."""
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "leaderboard" not in data:
        raise ValueError("Resposta inesperada de Blizzard")
    return data


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

def get_latest_season() -> int:
    """Busca i conserva temporalment l'ID de la temporada actual."""
    now = time.monotonic()
    with _lock:
        if _season_cache["value"] is not None and _season_cache["expires_at"] > now:
            return _season_cache["value"]
    try:
        data = blizzard_get({'region': 'EU', 'leaderboardId': 'battlegrounds'}, timeout=5)
        season_id = int(data['leaderboard']['seasonId'])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="No es pot consultar Blizzard ara mateix.")

    with _lock:
        _season_cache.update(value=season_id, expires_at=now + SEASON_CACHE_SECONDS)
    return season_id

def fetch_page(page: int, params: dict):
    """Descarrega una sola pàgina; els errors no interrompen tota la cerca."""
    p = params.copy()
    p['page'] = str(page)
    try:
        data = blizzard_get(p)
        return page, data.get('leaderboard', {}).get('rows', [])
    except (requests.RequestException, ValueError):
        return page, []

@app.get("/", response_class=HTMLResponse)
def llegir_index():
    try:
        with (APP_DIR / "index.html").open("r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Error: No s'ha trobat el fitxer 'index.html' a la mateixa carpeta!</h1>"

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/buscar")
def buscar_jugadors(request: Request, btags: str, mode: str = "battlegroundsduo", region: str = "EU"):
    if mode not in {"battlegrounds", "battlegroundsduo"}:
        raise HTTPException(status_code=400, detail="Mode no vàlid.")
    if region not in {"EU", "US", "AP"}:
        raise HTTPException(status_code=400, detail="Regió no vàlida.")

    client_ip = request.client.host if request.client else "unknown"
    if client_is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Massa consultes. Torna-ho a provar d'aquí a un minut.")

    season_id = get_latest_season()
    params = {'region': region, 'leaderboardId': mode, 'seasonId': str(season_id)}
    
    # Netegem i processem els noms que l'usuari ha introduït
    tags_introduits = [t.strip() for t in btags.replace('\n', ',').split(',') if t.strip()]
    if not tags_introduits:
        raise HTTPException(status_code=400, detail="Introdueix almenys un BattleTag.")
    if len(tags_introduits) > MAX_TAGS_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"Màxim de {MAX_TAGS_PER_REQUEST} BattleTags per consulta.")
    invalid_tags = [tag for tag in tags_introduits if not BTAG_PATTERN.fullmatch(tag)]
    if invalid_tags:
        raise HTTPException(status_code=400, detail="Un o més BattleTags no tenen un format vàlid.")

    cache_key = (tuple(sorted(tag.lower() for tag in tags_introduits)), mode, region, season_id)
    cached = cached_result(cache_key)
    if cached is not None:
        return cached
    
    # Creem l'estructura de cerca per controlar què ens falta trobar
    objectius = []
    for tag in tags_introduits:
        objectius.append({
            "original": tag,
            "lower": tag.lower(),
            "nom_sense_tag": tag.split('#')[0].lower()
        })
        
    # Inicialitzem tots els resultats com a "no trobats" per defecte
    resultats = {obj["original"]: {"btag": obj["original"], "found": False, "error": "No trobat (fora del top)"} for obj in objectius}
    objectius_pendents = objectius.copy()

    # 1. Obtenim la primera pàgina per saber el total de pàgines i mirar el Top 25
    try:
        data = blizzard_get({**params, 'page': '1'})
        total_pages = data.get('leaderboard', {}).get('pagination', {}).get('totalPages', 0)
        rows_p1 = data.get('leaderboard', {}).get('rows', [])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="No es pot consultar Blizzard ara mateix.")

    # Funció auxiliar per comprovar si els jugadors cercats estan a les files d'una pàgina
    def comprovar_jugadors_a_la_pagina(rows, num_pag):
        nonlocal objectius_pendents
        trobat_algun = False
        for row in rows:
            acc_id = row.get('accountid', '')
            acc_id_lower = acc_id.lower()
            
            for obj in list(objectius_pendents):
                # Coincidència exacta o que comenci pel mateix nom d'usuari
                if acc_id_lower == obj["lower"] or acc_id_lower.startswith(obj["nom_sense_tag"]):
                    resultats[obj["original"]] = {
                        "btag": acc_id,  # Retornem el BattleTag oficial amb les majúscules correctes de Blizzard
                        "rank": row.get('rank'),
                        "rating": row.get('rating'),
                        "found": True,
                        "page": num_pag
                    }
                    objectius_pendents.remove(obj)
                    trobat_algun = True
        return trobat_algun

    # Mirem si algun dels objectius és a la Pàgina 1
    comprovar_jugadors_a_la_pagina(rows_p1, 1)

    # Si ja els hem trobat tots a la pàgina 1, o no hi ha més pàgines, ja podem acabar
    if not objectius_pendents or total_pages <= 1:
        response = list(resultats.values())
        store_result(cache_key, response)
        return response

    # 2. Cerca en lots: limita la càrrega al servidor i a l'API de Blizzard.
    total_a_escanejar = min(total_pages, MAX_PAGES_TO_SCAN)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for page_start in range(2, total_a_escanejar + 1, MAX_WORKERS):
            pages = range(page_start, min(page_start + MAX_WORKERS, total_a_escanejar + 1))
            futures = [executor.submit(fetch_page, page, params) for page in pages]
            for future in concurrent.futures.as_completed(futures):
                num_pag, files_pag = future.result()
                if files_pag:
                    comprovar_jugadors_a_la_pagina(files_pag, num_pag)
            if not objectius_pendents:
                break
                        
    response = list(resultats.values())
    store_result(cache_key, response)
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
