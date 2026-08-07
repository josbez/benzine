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
import json
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
        # Include what we actually saw: a 403, a cookie wall, client-side
        # rendering and a genuine markup change all fail identically
        # otherwise, and the page cannot be inspected from wherever this
        # happens to be running.
        raise RuntimeError(
            "could not locate a Euro95 price on the UnitedConsumers page.\n"
            + diagnose(text)
        )
    return price


def diagnose(text: str, context: int = 90) -> str:
    """A report that distinguishes the ways this scrape can fail.

    The decisive question is whether any price-shaped token exists in the
    page text at all. If none does, the prices are rendered client-side and
    no amount of parsing will find them -- the fix is to call whatever
    endpoint the page's own JavaScript calls, not to widen a regex.
    """
    prices = _PRICE.findall(text)
    lowered = text.lower()

    lines = [
        f"page text: {len(text)} chars",
        f"price-shaped tokens found anywhere: {len(prices)} {prices[:10]}",
    ]

    for label in _LABELS:
        hits = []
        start = 0
        while (idx := lowered.find(label, start)) != -1 and len(hits) < 3:
            start = idx + 1
            hits.append(text[max(0, idx - 20) : idx + context])
        lines.append(f"label {label!r}: {len(hits)} shown {hits}")

    if not prices:
        lines.append(
            "VERDICT: no price anywhere in the page text -- the figures are "
            "almost certainly rendered client-side; find the JSON endpoint "
            "the page calls instead of parsing HTML."
        )
    lines.append(f"first 400 chars: {text[:400]!r}")
    return "\n".join(lines)


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


# --------------------------------------------------------------------------
# finding the price when it is not in the page text
#
# `diagnose()` answers "is there a price in the text?". When the answer is
# no, as it was on 7 August 2026, the next question is "then where is it?"
# -- and that question cannot be answered from a laptop that cannot reach
# the page. So it is answered here, by code that runs on the runner.
#
# The first place to look is deliberately *inside* the script tags that
# `to_text()` strips. Server-rendered frameworks (Next.js, Nuxt, SvelteKit)
# ship the page's data as a JSON blob in the HTML, so "rendered
# client-side" and "absent from the HTML" are not the same thing, and the
# verdict in `diagnose()` cannot tell them apart.

_SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.S | re.I)

# Paths and URLs that look like they return data rather than markup.
_ENDPOINT = re.compile(
    r"""["'`](https?://[^"'`\s<>]+|/[^"'`\s<>]*)"""
    r"""(?=[^"'`]*?(?:api|graphql|\.json|/data/))([^"'`\s<>]*)["'`]""",
    re.I,
)

# Keys worth reporting even when their value is not price-shaped: they say
# which part of the payload to look in.
_DATA_KEYS = (
    "euro", "benzine", "e10", "advies", "brandstof", "fuel", "prijs", "price",
)

_MAX_HITS = 12


def probe(html: str | None = None, follow: bool = False) -> str:
    """Report where on the page the advisory price might actually live.

    Args:
        html: page source; fetched if omitted.
        follow: also request the candidate endpoints found in the markup
            and report which of them return a price. Off by default so the
            report stays offline-safe.
    """
    if html is None:
        response = requests.get(_URL, timeout=_TIMEOUT, headers=_HEADERS)
        response.raise_for_status()
        html = response.text

    lines = [f"page source: {len(html)} chars"]
    lines += _report_embedded_json(html)

    endpoints = find_endpoints(html)
    lines.append("")
    lines.append(f"candidate data endpoints in the markup: {len(endpoints)}")
    lines += [f"  {url}" for url in endpoints[:_MAX_HITS]]

    if follow and endpoints:
        lines.append("")
        lines.append("fetching candidates:")
        lines += _report_fetched(endpoints[:_MAX_HITS])

    return "\n".join(lines)


def _report_embedded_json(html: str) -> list[str]:
    """Prices hiding in JSON inside <script> tags."""
    lines = []
    for label, payload in embedded_json(html):
        prices, keys = [], []
        for path, value in _walk(payload):
            if _price_like(value):
                prices.append(f"{path} = {value!r}")
            elif any(k in path.lower() for k in _DATA_KEYS):
                keys.append(f"{path} = {_short(value)}")

        lines.append("")
        lines.append(f"embedded JSON {label}: {len(prices)} price-shaped values")
        lines += [f"  PRICE {p}" for p in prices[:_MAX_HITS]]
        lines += [f"  key   {k}" for k in keys[:_MAX_HITS]]
        if prices:
            lines.append(
                "  VERDICT: the price is in the HTML after all -- parse this "
                "JSON blob instead of the page text."
            )
    if not lines:
        lines.append("")
        lines.append("no parseable JSON found in any <script> tag")
    return lines


def embedded_json(html: str):
    """Yield (label, parsed) for every script tag holding JSON.

    Covers the two shapes that matter: a `<script type="application/json">`
    whose whole body is the payload, and an assignment such as
    `window.__NUXT__ = {...}` where the payload is a substring.
    """
    for attrs, body in _SCRIPT.findall(html):
        body = body.strip()
        if not body:
            continue
        label = _script_label(attrs)
        for candidate in (body, _braced(body)):
            if not candidate:
                continue
            try:
                yield label, json.loads(candidate)
            except (ValueError, TypeError):
                continue
            break


def _script_label(attrs: str) -> str:
    ident = re.search(r"""id=["']([^"']+)["']""", attrs, re.I)
    kind = re.search(r"""type=["']([^"']+)["']""", attrs, re.I)
    return ident.group(1) if ident else (kind.group(1) if kind else "<inline>")


def _braced(body: str) -> str | None:
    """The outermost {...} in a script body, for `window.x = {...};` forms."""
    start, end = body.find("{"), body.rfind("}")
    return body[start : end + 1] if 0 <= start < end else None


def _walk(node, path: str = "$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        # Only the first few entries: a price list is short, and a page's
        # worth of navigation items is not worth printing.
        for i, value in enumerate(node[:20]):
            yield from _walk(value, f"{path}[{i}]")
    else:
        yield path, node


def _price_like(value) -> bool:
    """A number that could be a euro-per-litre pump price."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0.8 < float(value) < 4.0
    if isinstance(value, str) and _PRICE.fullmatch(value.strip()):
        return True
    return False


def _short(value, limit: int = 60) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def find_endpoints(html: str) -> list[str]:
    """Distinct API-ish URLs mentioned anywhere in the page source."""
    seen = {}
    for head, tail in _ENDPOINT.findall(html):
        url = (head + tail).strip()
        # Assets are the bulk of the matches and never carry prices.
        if url.endswith((".js", ".css", ".png", ".jpg", ".svg", ".woff2")):
            continue
        seen.setdefault(url, None)
    return sorted(seen)


def _report_fetched(endpoints: list[str]) -> list[str]:
    lines = []
    for url in endpoints:
        target = url if url.startswith("http") else _origin() + url
        try:
            response = requests.get(target, timeout=_TIMEOUT, headers=_HEADERS)
            body = response.text
        except Exception as exc:  # noqa: BLE001 - this is the report
            lines.append(f"  {target} -> {type(exc).__name__}: {exc}")
            continue

        prices = _PRICE.findall(body) + re.findall(r"\b[123]\.\d{2,3}\b", body)
        verdict = f"{len(prices)} price-shaped tokens {prices[:5]}"
        lines.append(f"  {target} -> HTTP {response.status_code}, {verdict}")
    return lines


def _origin() -> str:
    scheme, _, rest = _URL.partition("://")
    return f"{scheme}://{rest.split('/')[0]}"
