# Local leaderboard archives

Completed leaderboard seasons are stored here on the production server after
running `archive_leaderboards.py`. The JSON files are intentionally ignored by
Git: they are a generated local cache of public leaderboard data, not source
code.

The scanner reads completed seasons from this directory. Current-season searches
read the separate local snapshots in `current_leaderboards/`. Do not delete an archive unless you intend to rebuild it.

New builds default to an exclusive 8,000 MMR floor and record it as `minRating` with `minRatingInclusive: false`.
Older archives may have different coverage. Existing archives are kept unchanged.
Players at or below the floor are not included in these historical searches.
