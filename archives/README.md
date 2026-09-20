# Local leaderboard archives

Completed leaderboard seasons are stored here on the production server after
running `archive_leaderboards.py`. The JSON files are intentionally ignored by
Git: they are a generated local cache of public leaderboard data, not source
code.

The scanner reads a completed season from this directory and checks only the
current season live. Do not delete an archive unless you intend to rebuild it.
