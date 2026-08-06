"""Freshness rules for the on-disk source caches.

Every source here caches its download in ``data/raw``. Without an expiry
that cache is not a cache but a snapshot: the first run of the month wins
and every later run silently reuses it. That is invisible locally -- the
forecast still builds, it is simply built on old prices -- so the check
lives in one place rather than being remembered per source.

Age is taken from the file's modification time, not from the newest row in
it. "When did we last ask the source?" is the question that decides whether
to ask again; a series that legitimately has no new rows (a weekend, a week
without a CBS release) would otherwise be re-downloaded forever.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

# Both live feeds publish at most once a day, so anything fetched within
# the last twelve hours is as current as the source can be.
DEFAULT_MAX_AGE = dt.timedelta(hours=12)


def is_fresh(path: Path, max_age: dt.timedelta = DEFAULT_MAX_AGE) -> bool:
    """Whether ``path`` was written recently enough to reuse."""
    if not path.exists():
        return False
    age = dt.datetime.now() - dt.datetime.fromtimestamp(path.stat().st_mtime)
    return age < max_age
