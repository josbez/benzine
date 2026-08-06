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

# A browser-ish User-Agent: some sites answer 403 to obviously scripted
# clients, and a silent 403 is indistinguishable from a markup change.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 benzine-forecaster/0.1"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
}

# Dutch decimal comma, 2 or 3 places: "2,10" or "2,109".
_PRICE = re.compile(r"\b(\d,\d{2,3})\b")
_LABELS = ("euro 95", "euro95", "euro-95", "benzine")

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_MARKUP = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[\s ]+")


def scrape(html: str | None = None) -> float:
    """Today's Euro95 advisory price in EUR per litre.

    Parsing runs on the *text* of the page rather than its markup. Labels
    and values usually sit in separate cells with a lot of HTML between
    them, so matching against raw markup needs a huge search window and
    picks up attribute values by accident; stripping tags first collapses
    that distance to a few characters.
    """
    if html is None:
        response = requests.get(_URL, timeout=_TIMEOUT, headers=_HEADERS)
        response.raise_for_status()
        html = response.text

    text = to_text(html)
    price = find_price(text)
    if price is None:
        # Include what we actually saw: a 403, a cookie wall and a genuine
        # markup change all fail identically otherwise, and the page cannot
        # be inspected from wherever this happens to be running.
        raise RuntimeError(
            "could not locate a Euro95 price on the UnitedConsumers page. "
            "The markup may have changed, the response may be a block page, "
            "or the prices may be rendered client-side. First 600 characters "
            f"of the page text follow:\n{text[:600]!r}"
        )
    return price


def to_text(html: str) -> str:
    """Page text with scripts, tags and runs of whitespace removed."""
    return _SPACE.sub(" ", _MARKUP.sub(" ", _TAG.sub(" ", html))).strip()


def find_price(text: str, span: int = 120) -> float | None:
    """First plausible petrol price appearing shortly after a fuel label.

    Scans every label occurrence, not just the first: navigation and
    breadcrumbs mention "benzine" long before the table does.
    """
    lowered = text.lower()
    for label in _LABELS:
        start = 0
        while (idx := lowered.find(label, start)) != -1:
            start = idx + 1
            for match in _PRICE.finditer(text[idx : idx + span]):
                value = float(match.group(1).replace(",", "."))
                if 0.8 < value < 4.0:
                    return value
    return None


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
