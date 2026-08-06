"""CBS StatLine table 80416ned: daily average pump prices.

This is the long, authoritative history and it is what we train against.
It is *not* a real-time signal: CBS publishes the daily prices up to and
including Monday on the Thursday of that same week. Every other day has to
wait for the next release. Ignoring that lag is the single easiest way to
build a backtest that looks excellent and fails in production, so the lag
is modelled explicitly here in `publication_date`.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import CBS_BASE, CBS_TABLE, RAW

_TIMEOUT = 60


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
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    url = f"{CBS_BASE}/{CBS_TABLE}/TypedDataSet?$format=json"
    rows: list[dict] = []
    while url:
        payload = requests.get(url, timeout=_TIMEOUT).json()
        rows.extend(payload.get("value", []))
        url = payload.get("odata.nextLink") or payload.get("@odata.nextLink")

    if not rows:
        raise RuntimeError(f"CBS returned no rows for table {CBS_TABLE}")

    df = _normalise(pd.DataFrame(rows))
    df.to_parquet(cache, index=False)
    return df


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
