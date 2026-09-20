# On-demand live mode

Set **`HSBG_DATA_MODE=live`** before starting the API. See [local setup](Local-setup.md) for Linux/macOS and PowerShell commands.

## What “live” means

The current-season lookup queries Blizzard's public leaderboard during the search. It does not wait for the half-hour snapshot job. No current snapshots are required, although existing snapshots or archives can help the search choose likely pages.

This is not a real-time game feed. Blizzard controls how fresh its public data is, and a leaderboard can move while pages are being scanned. HSBG shows when the lookup finished, not when Blizzard last updated each player.

Each new current-season search performs an upstream lookup. Completed live history results are not reused from the result cache. Current season metadata is cached for up to 10 minutes. Historical seasons still come from local archives.

## Request limits

| Setting | Live-mode default | Meaning |
| --- | --- | --- |
| `MAX_PAGES_TO_SCAN` | `40` | Total page budget, including page one. An unfinished scan reports an incomplete result. |
| `MAX_WORKERS` | `4` | Concurrent page fetches, clamped to 1–4. |
| `MAX_CONCURRENT_SEARCHES` | `2` | Shared limit on simultaneous upstream search operations. |
| `SEARCH_QUEUE_WAIT_SECONDS` | `180` | Maximum time waiting for a search slot. |
| `RATE_LIMIT_REQUESTS` | `10` | Searches per IP per rate-limit window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window in seconds. |

Page submissions are spaced by 0.25 seconds. A failed page stops additional batches; already submitted requests finish. Upstream errors are reported rather than retried indefinitely.

Forty pages is a safety budget, not a promise to cover every player. The search first checks page one, then saved rank neighborhoods when available, then scans from the end. It may miss a player outside the inspected pages; that outcome is marked incomplete.

For a larger personal lookup, for example:

```bash
HSBG_DATA_MODE=live MAX_PAGES_TO_SCAN=100 MAX_WORKERS=2 uvicorn backend:app --host 127.0.0.1 --port 8000
```

`MAX_PAGES_TO_SCAN=0` removes the page cap; it can require a very large scan. Prefer a finite budget and low concurrency. One HSBG search can generate many Blizzard requests. Do not run multiple copies to evade upstream limits.

## Returning to snapshots

Stop the API, set `HSBG_DATA_MODE=snapshot`, ensure snapshots exist, and restart. The public site continues to use snapshot mode by default.
