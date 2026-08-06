"""Wholesale market inputs: crude, refined gasoline, and the euro.

The price that actually drives Dutch pumps is the Rotterdam Eurobob (EBOB)
barge assessment, which is a paid Argus/Platts product. As a free stand-in
we use RBOB gasoline futures plus EUR/USD, which tracks EBOB closely enough
for a prototype: both are refined-gasoline cracks off the same crude barrel.
Swap `SERIES` for a real EBOB feed if you have a licence -- nothing
downstream needs to change.

Each series is tried against several providers in turn. That is not
belt-and-braces: free market data is exactly the kind of dependency that
answers fine from a laptop and returns a block page from a cloud runner,
which is what stooq does from GitHub's Azure ranges. One provider is a
single point of failure for the entire daily job.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import RAW

_TIMEOUT = 60
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; benzine-forecaster/0.1)"}

# Logical series -> (yahoo symbol, stooq symbol).
SERIES = {
    "rbob": ("RB=F", "rb.f"),      # RBOB gasoline, USD/gallon
    "brent": ("BZ=F", "cb.f"),     # Brent crude, USD/barrel
    "eurusd": ("EURUSD=X", "eurusd"),  # USD per EUR
}

GALLONS_PER_LITRE = 1.0 / 3.785411784
BARRELS_PER_LITRE = 1.0 / 158.987294928


def fetch(force: bool = False) -> pd.DataFrame:
    """Daily market series, converted to EUR per litre where meaningful."""
    cache = RAW / "market.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    frames = {}
    for name, (yahoo_symbol, stooq_symbol) in SERIES.items():
        frames[name] = _first_working(name, yahoo_symbol, stooq_symbol)

    df = pd.concat(frames, axis=1)
    df.columns = list(frames)
    df = df.sort_index()

    # Markets are shut at weekends; the pump is not. Carry the last close
    # forward so every calendar day has a price.
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D")).ffill()
    df.index.name = "date"

    df["rbob_eur_l"] = df["rbob"] * GALLONS_PER_LITRE / df["eurusd"]
    df["brent_eur_l"] = df["brent"] * BARRELS_PER_LITRE / df["eurusd"]

    out = df.reset_index()
    out.to_parquet(cache, index=False)
    return out


def _first_working(name: str, yahoo_symbol: str, stooq_symbol: str) -> pd.Series:
    """Fetch one series, trying each provider and reporting what happened."""
    attempts = (("yahoo", _yahoo, yahoo_symbol), ("stooq", _stooq, stooq_symbol))
    failures = []

    for provider, fn, symbol in attempts:
        try:
            series = fn(symbol)
        except Exception as exc:  # noqa: BLE001 - try the next provider
            failures.append(f"{provider}({symbol}): {type(exc).__name__}: {exc}")
            continue
        if series.empty:
            failures.append(f"{provider}({symbol}): empty series")
            continue
        print(f"    {name}: {len(series)} rows from {provider}")
        return series

    raise RuntimeError(
        f"no provider returned data for {name!r}. Attempts:\n  "
        + "\n  ".join(failures)
    )


def _yahoo(symbol: str) -> pd.Series:
    """Daily closes from the Yahoo Finance chart endpoint."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=15y&interval=1d"
    )
    response = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS)
    response.raise_for_status()
    payload = response.json()

    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"chart error: {error}")

    result = payload["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    index = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None)

    series = pd.Series(closes, index=index.normalize(), name=symbol)
    return series.dropna()


def _stooq(symbol: str) -> pd.Series:
    """Daily closes from stooq's free CSV endpoint.

    Note this is routinely blocked from datacentre IP ranges, in which case
    an HTML page comes back where the CSV should be.
    """
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    response = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS)
    response.raise_for_status()
    text = response.text

    if not text.lstrip().lower().startswith("date"):
        raise RuntimeError(f"expected CSV, got {text[:120]!r}")

    frame = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    return frame.set_index("Date")["Close"].dropna().rename(symbol)
