"""Wholesale market inputs: crude, refined gasoline, and the euro.

The price that actually drives Dutch pumps is the Rotterdam Eurobob (EBOB)
barge assessment, which is a paid Argus/Platts product. As a free stand-in
we use RBOB gasoline futures plus EUR/USD, which tracks EBOB closely enough
for a prototype: both are refined-gasoline cracks off the same crude barrel.
Swap `SERIES` for a real EBOB feed if you have a licence -- nothing
downstream needs to change.

Each series is tried against several providers in turn, and each provider
is tried several times. That is not belt-and-braces: free market data is
exactly the kind of dependency that answers fine from a laptop and returns
a block page from a cloud runner, which is what stooq does from GitHub's
Azure ranges. One provider is a single point of failure for the entire
daily job -- and since a failed job also costs a day of advisory-price
history, a single network hiccup used to be permanently expensive.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import RAW
from . import cache as cache_policy
from . import retry

_TIMEOUT = 60
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; benzine-forecaster/0.1)"}

# Retries are per provider, not per series: a provider that answers a
# block page will answer it again, so they are there for transient faults
# (timeouts, 5xx, a truncated response) and hand over to the next provider
# quickly. The schedule itself is shared with the other sources.
_ATTEMPTS = retry.ATTEMPTS

# Yahoo accepts a range; asking for twenty years of history every morning is
# both wasteful and a good way to get rate-limited. With a cache in hand we
# ask for a window instead, wide enough to survive a fortnight of failed
# runs and any revisions inside it.
_FULL_RANGE = "max"
_TOPUP_RANGE = "6mo"

# Logical series -> (yahoo symbol, stooq symbol).
SERIES = {
    "rbob": ("RB=F", "rb.f"),      # RBOB gasoline, USD/gallon
    "brent": ("BZ=F", "cb.f"),     # Brent crude, USD/barrel
    "eurusd": ("EURUSD=X", "eurusd"),  # USD per EUR
}

GALLONS_PER_LITRE = 1.0 / 3.785411784
BARRELS_PER_LITRE = 1.0 / 158.987294928


RAW_COLUMNS = list(SERIES)


def fetch(force: bool = False) -> pd.DataFrame:
    """Daily market series, converted to EUR per litre where meaningful."""
    cache = RAW / "market.parquet"
    # `force` means "start over": it discards the cached history rather
    # than topping it up, which is the only way to repair a cache that has
    # gone bad without deleting files by hand.
    cached = pd.read_parquet(cache) if cache.exists() and not force else None

    if cached is not None and cache_policy.is_fresh(cache):
        return cached

    # The full history is downloaded once; after that we only ask for a
    # recent window and splice it onto what we already have. CBS pump
    # prices go back to 2006 and any market history shorter than that is
    # training data thrown away for nothing -- but that argues for keeping
    # the history, not for re-downloading it every morning.
    window = _FULL_RANGE if cached is None else _TOPUP_RANGE

    frames = {}
    for name, (yahoo_symbol, stooq_symbol) in SERIES.items():
        frames[name] = _first_working(name, yahoo_symbol, stooq_symbol, window)

    fresh = pd.concat(frames, axis=1)
    fresh.columns = list(frames)

    out = _derive(_splice(cached, fresh))
    out.to_parquet(cache, index=False)
    return out


def _splice(cached: pd.DataFrame | None, fresh: pd.DataFrame) -> pd.DataFrame:
    """Lay a freshly fetched window over the cached history.

    Newly fetched rows win on overlapping dates: providers do revise a
    close after the fact, and the window is fetched precisely to pick those
    revisions up.
    """
    if cached is None:
        return fresh.sort_index()

    old = cached.set_index("date")[RAW_COLUMNS]
    combined = pd.concat([old, fresh.reindex(columns=RAW_COLUMNS)])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def _derive(raw: pd.DataFrame) -> pd.DataFrame:
    """Fill the calendar and convert to euro per litre."""
    # Markets are shut at weekends; the pump is not. Carry the last close
    # forward so every calendar day has a price.
    df = raw.reindex(pd.date_range(raw.index.min(), raw.index.max(), freq="D")).ffill()
    df.index.name = "date"

    df["rbob_eur_l"] = df["rbob"] * GALLONS_PER_LITRE / df["eurusd"]
    df["brent_eur_l"] = df["brent"] * BARRELS_PER_LITRE / df["eurusd"]
    return df.reset_index()


def _first_working(
    name: str, yahoo_symbol: str, stooq_symbol: str, window: str = _FULL_RANGE
) -> pd.Series:
    """Fetch one series, trying each provider and reporting what happened."""
    attempts = (("yahoo", _yahoo, yahoo_symbol), ("stooq", _stooq, stooq_symbol))
    failures = []

    for provider, fn, symbol in attempts:
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                series = fn(symbol, window)
            except Exception as exc:  # noqa: BLE001 - retry, then next provider
                failures.append(
                    f"{provider}({symbol}) try {attempt}: {type(exc).__name__}: {exc}"
                )
            else:
                if not series.empty:
                    print(f"    {name}: {len(series)} rows from {provider}")
                    return series
                # An empty series is a valid HTTP response with nothing in
                # it -- a blocked symbol, not a transient fault. Retrying
                # only burns time, so hand over to the next provider.
                failures.append(f"{provider}({symbol}) try {attempt}: empty series")
                break
            if attempt < _ATTEMPTS:
                retry.sleep_before_retry(attempt)

    raise RuntimeError(
        f"no provider returned data for {name!r}. Attempts:\n  "
        + "\n  ".join(failures)
    )


def _yahoo(symbol: str, window: str = _FULL_RANGE) -> pd.Series:
    """Daily closes from the Yahoo Finance chart endpoint."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={window}&interval=1d"
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


def _stooq(symbol: str, window: str = _FULL_RANGE) -> pd.Series:
    """Daily closes from stooq's free CSV endpoint.

    ``window`` is accepted and ignored: this endpoint has no range
    parameter and always returns the full series. That costs nothing here,
    because the caller splices whatever it gets onto the cached history.

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
