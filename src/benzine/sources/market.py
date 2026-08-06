"""Wholesale market inputs: crude, refined gasoline, and the euro.

The price that actually drives Dutch pumps is the Rotterdam Eurobob (EBOB)
barge assessment, which is a paid Argus/Platts product. As a free stand-in
we use RBOB gasoline futures plus EUR/USD, which tracks EBOB closely enough
for a prototype: both are refined-gasoline cracks off the same crude barrel.
Swap `_STOOQ_SYMBOLS` for a real EBOB feed if you have a licence -- nothing
downstream needs to change.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import RAW

_TIMEOUT = 60

# Stooq serves free daily CSV history without an API key.
_STOOQ_SYMBOLS = {
    "brent": "cb.f",     # Brent crude, USD/barrel
    "rbob": "rb.f",      # RBOB gasoline, USD/gallon
    "eurusd": "eurusd",  # USD per EUR
}

GALLONS_PER_LITRE = 1.0 / 3.785411784
BARRELS_PER_LITRE = 1.0 / 158.987294928


def fetch(force: bool = False) -> pd.DataFrame:
    """Daily market series, converted to EUR per litre where meaningful."""
    cache = RAW / "market.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    frames = {name: _stooq(sym) for name, sym in _STOOQ_SYMBOLS.items()}
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


def _stooq(symbol: str) -> pd.Series:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    text = requests.get(url, timeout=_TIMEOUT).text
    if not text.lstrip().lower().startswith("date"):
        raise RuntimeError(f"stooq returned no data for {symbol!r}: {text[:120]!r}")
    frame = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    return frame.set_index("Date")["Close"].rename(symbol)
