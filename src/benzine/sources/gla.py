"""UnitedConsumers "gemiddelde landelijke adviesprijs" (GLA).

The GLA is the average of the recommended prices published by BP, Esso,
Shell, Texaco and TotalEnergies. It matters here because it is the only
national petrol figure available *the same day* -- CBS lags by up to nine
days. So the GLA is what anchors a live forecast to reality.

There is no public archive of past GLA values, so this module keeps an
append-only history: scrape once a day and the file grows into the series
you need. Until it has depth, the model falls back to CBS alone.
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import requests

from ..config import RAW

_URL = "https://www.unitedconsumers.com/tanken/info/gemiddelde-landelijke-adviesprijs"
_TIMEOUT = 30
_STORE = RAW / "gla_history.csv"

# Prices sit in the page as "2,109" or "€ 2,109" near the fuel name. The
# site's markup changes from time to time; `scrape` raises loudly rather
# than silently returning a wrong number.
_PRICE = re.compile(r"(\d,\d{2,3})")


def scrape(html: str | None = None) -> float:
    """Today's Euro95 advisory price in EUR per litre."""
    if html is None:
        html = requests.get(
            _URL, timeout=_TIMEOUT, headers={"User-Agent": "benzine-forecaster/0.1"}
        ).text

    window = _euro95_window(html)
    match = _PRICE.search(window)
    if not match:
        raise RuntimeError(
            "could not locate a Euro95 price on the UnitedConsumers page; "
            "the markup likely changed -- check sources/gla.py"
        )
    price = float(match.group(1).replace(",", "."))
    if not 0.8 < price < 4.0:
        raise RuntimeError(f"implausible Euro95 advisory price parsed: {price}")
    return price


def _euro95_window(html: str, span: int = 400) -> str:
    """The slice of markup just after the first Euro95 mention."""
    for needle in ("euro 95", "euro95", "benzine"):
        idx = html.lower().find(needle)
        if idx != -1:
            return html[idx : idx + span]
    return html


def record_today(price: float | None = None, date: dt.date | None = None) -> pd.DataFrame:
    """Append today's GLA to the local history and return the full series."""
    date = date or dt.date.today()
    price = scrape() if price is None else price

    history = load()
    history = history[history["date"] != pd.Timestamp(date)]
    row = pd.DataFrame([{"date": pd.Timestamp(date), "gla_euro95": price}])
    history = (
        pd.concat([history, row], ignore_index=True)
        .sort_values("date")
        .reset_index(drop=True)
    )
    history.to_csv(_STORE, index=False)
    return history


def load() -> pd.DataFrame:
    if not _STORE.exists():
        return pd.DataFrame(columns=["date", "gla_euro95"])
    return pd.read_csv(_STORE, parse_dates=["date"])
