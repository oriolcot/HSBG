# HSBG guides

HSBG searches public Battlegrounds MMR, regional ranks and archived seasons.

- **[Install locally](https://github.com/oriolcot/HSBG/blob/main/docs/wiki/Local-setup.md)** — Python, installation and your first search.
- **[On-demand live mode](https://github.com/oriolcot/HSBG/blob/main/docs/wiki/Live-mode.md)** — query Blizzard when you search, without a snapshot refresh schedule.
- **[Host your own instance](https://github.com/oriolcot/HSBG/blob/main/docs/wiki/Self-hosting.md)** — HTTPS, process isolation and choosing a data mode.

| Mode | Current-season data | Requires downloaded snapshots? |
| --- | --- | --- |
| `snapshot` (default) | Latest successful local capture | Yes |
| `live` (opt-in) | Public Blizzard leaderboard queried on demand | No |

Historical seasons use local archives in both modes. No Battle.net credentials are needed.

The public [hsbg.win](https://hsbg.win) instance uses snapshots, scheduled approximately every 30 minutes. On-demand mode is intended primarily for personal installations: it can be slower, and one player search can require many upstream page requests.

These pages are maintained in the repository. This Home page can also be pasted into the GitHub Wiki; its links work from either location.
