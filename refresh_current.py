#!/usr/bin/env python3
"""Refresh complete, dated snapshots of the live public leaderboards."""
import argparse
import fcntl
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import archive_leaderboards as upstream

SNAPSHOT_DIR = Path(__file__).resolve().parent / 'current_leaderboards'


def refresh_board(region, mode):
    params = {'region': region, 'leaderboardId': mode}
    started = datetime.now(UTC).isoformat()
    first = upstream.get_json({**params, 'page': '1'}, 15, 3)
    season = int(first['seasonId'])
    pages = int(first['leaderboard']['pagination']['totalPages'])
    if pages < 1:
        raise ValueError('No current leaderboard pages; retaining previous snapshot')

    def fetch(page):
        data = first if page == 1 else upstream.get_json(
            {**params, 'seasonId': str(season), 'page': str(page)}, 15, 3)
        if int(data['seasonId']) != season:
            raise ValueError('Season changed during capture')
        rows = data['leaderboard']['rows']
        if not rows:
            raise ValueError(f'Empty page {page}; retaining previous snapshot')
        return upstream.compact_rows(rows)

    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        page = 1
        while page <= pages:
            size = upstream.batch_size(4)
            futures = []
            for number in range(page, min(page + size, pages + 1)):
                time.sleep(.25)
                futures.append(pool.submit(fetch, number))
            for future in futures:
                rows.extend(future.result())
            page += len(futures)
            print(f'current {region} {mode}: page {page-1}/{pages}', flush=True)
    # A live board moves while it is read: this is a search hint, never proof of absence.
    latest = upstream.get_json({**params, 'page': '1'}, 15, 3)
    if int(latest['seasonId']) != season:
        raise ValueError('Season changed before publication; retaining previous snapshot')
    document = {'season': season, 'region': region, 'mode': mode,
                'captureStartedAt': started, 'capturedAt': datetime.now(UTC).isoformat(),
                'totalPages': pages, 'pageSize': 25, 'rows': rows}
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOT_DIR / f'{region}-{mode}.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    os.replace(temporary, target)
    print(f'complete current {region} {mode}: {len(rows)} entries, season ID {season}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    boards = [(region, mode) for region in ('EU', 'US', 'AP')
              for mode in ('battlegrounds', 'battlegroundsduo')]
    if args.scheduled:
        # UTC minute slots repeat every half hour; missed slots are not replayed.
        slot = (datetime.now(UTC).minute % 30) // 5
        boards = [boards[slot]]
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with (SNAPSHOT_DIR / '.refresh.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A refresh is already running; skipping.', flush=True)
            return
        upstream._worker_limit = 4
        failures = []
        for region, mode in boards:
            try:
                refresh_board(region, mode)
            except Exception as error:
                failures.append(f'{region} {mode}: {error}')
                print(f'FAILED current {failures[-1]}', flush=True)
        if failures:
            raise SystemExit('\n'.join(failures))
        print('Selected current leaderboard snapshots refreshed.', flush=True)


if __name__ == '__main__':
    main()
