"""CBS StatLine table 80416ned: daily average pump prices.

This is the long, authoritative history and it is what we train against.
It is *not* a real-time signal: CBS publishes the daily prices up to and
including Monday on the Thursday of that same week. Every other day has to
wait for the next release. Ignoring that lag is the single easiest way to
build a backtest that looks excellent and fails in production, so the lag
is modelled explicitly here in `publication_date`.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from ..config import CBS_BASE, CBS_TABLE, RAW
from . import cache as cache_policy

_TIMEOUT = 60

# Longer than the market cache on purpose. CBS releases once a week, so
# re-downloading the whole table on every one of the day's runs would be
# three times the traffic for the same numbers; eight hours still picks
# the Thursday morning release up within the same morning. What this must
# not be is never: a cache with no expiry turns a local run into a run
# against whatever prices happened to be current the first time.
_MAX_CACHE_AGE = dt.timedelta(hours=8)

# How stale the cache may be before a failed refresh becomes a hard error
# rather than a fallback. One CBS release cycle: past this we would be
# missing a publication, not merely repeating one.
_MAX_FALLBACK_AGE = dt.timedelta(days=7)


def publication_date(observation_date: pd.Timestamp) -> pd.Timestamp:
    """When a given day's price first becomes publicly available.

    CBS releases on Thursday, covering days through the Monday of that week.
    So a price for day ``d`` lands on the first Thursday strictly after the
    first Monday falling on or after ``d``.

    >>> publication_date(pd.Timestamp("2026-03-02"))  # a Monday
    Timestamp('2026-03-05 00:00:00')
    >>> publication_date(pd.Timestamp("2026-03-03"))  # the Tuesday after
    Timestamp('2026-03-12 00:00:00')
    """
    d = pd.Timestamp(observation_date).normalize()
    days_to_monday = (0 - d.dayofweek) % 7
    monday = d + pd.Timedelta(days=days_to_monday)
    # Thursday is weekday 3; we want the first one strictly after `monday`.
    days_to_thursday = (3 - monday.dayofweek) % 7
    if days_to_thursday == 0:
        days_to_thursday = 7
    return monday + pd.Timedelta(days=days_to_thursday)


def fetch(force: bool = False) -> pd.DataFrame:
    """Download the full daily price table, caching the raw payload."""
    cache = RAW / f"cbs_{CBS_TABLE}.parquet"
    if not force and cache_policy.is_fresh(cache, _MAX_CACHE_AGE):
        return pd.read_parquet(cache)

    try:
        df = _download()
    except Exception as exc:  # noqa: BLE001 - a recent table beats no table
        # Stale prices are still real prices, and the age of the newest one
        # is carried through to the UI as `staleness_days`. Failing here
        # instead would, under `--source auto`, fall through to the
        # synthetic generator: numbers that are not prices at all.
        #
        # Bounded, though. Past a release cycle we are no longer absorbing
        # an outage, we are quietly serving a table that is missing a
        # publication -- and that should be a red run.
        if not cache_policy.is_fresh(cache, _MAX_FALLBACK_AGE):
            raise
        print(f"  CBS refresh failed ({type(exc).__name__}: {exc}); using the cache")
        return pd.read_parquet(cache)

    df.to_parquet(cache, index=False)
    return df


def _download() -> pd.DataFrame:
    url = f"{CBS_BASE}/{CBS_TABLE}/TypedDataSet?$format=json"
    rows: list[dict] = []
    while url:
        payload = requests.get(url, timeout=_TIMEOUT).json()
        rows.extend(payload.get("value", []))
        url = payload.get("odata.nextLink") or payload.get("@odata.nextLink")

    if not rows:
        raise RuntimeError(f"CBS returned no rows for table {CBS_TABLE}")
    return _normalise(pd.DataFrame(rows))


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    """Reshape the CBS payload into date / euro95 / diesel / lpg columns."""
    period_col = next(c for c in raw.columns if c.lower().startswith("perioden"))
    df = raw.rename(columns={period_col: "period"})

    # CBS day periods look like "2026JJ00" / "2026MM03DD05"; the ISO-ish
    # variants parse directly, the rest we decode by hand.
    df["date"] = df["period"].map(_parse_cbs_day)
    df = df.dropna(subset=["date"])

    colmap = {}
    for col in df.columns:
        low = col.lower()
        if "euro95" in low or "benzine" in low:
            colmap[col] = "euro95"
        elif "diesel" in low:
            colmap[col] = "diesel"
        elif "lpg" in low:
            colmap[col] = "lpg"
    df = df.rename(columns=colmap)

    keep = ["date"] + [c for c in ("euro95", "diesel", "lpg") if c in df.columns]
    out = df[keep].copy()
    for c in keep[1:]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["euro95"]).sort_values("date").reset_index(drop=True)
    out["available_from"] = out["date"].map(publication_date)
    return out


def _parse_cbs_day(period: str) -> pd.Timestamp | float:
    """Decode a CBS period string into a date, or NaT if it is not a day."""
    period = str(period).strip()
    if "MM" in period and "DD" in period:
        year = int(period[:4])
        month = int(period.split("MM")[1][:2])
        day = int(period.split("DD")[1][:2])
        try:
            return pd.Timestamp(year=year, month=month, day=day)
        except ValueError:
            return pd.NaT
    try:
        return pd.Timestamp(period)
    except (ValueError, TypeError):
        return pd.NaT
