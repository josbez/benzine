"""A synthetic stand-in for the real feeds, for development and CI.

This exists so the pipeline can be exercised end to end without network
access. It is emphatically *not* a substitute for real data: backtest
numbers produced on this generator measure whether the machinery works,
not how accurate the forecaster will be in the Netherlands.

The generating process mirrors the structure we believe the real market
has, so that a model which is genuinely picking up pass-through will beat
the naive baseline here, and one that is merely overfitting will not:

  * crude is a random walk with fat-ish tails -- unforecastable
  * refined gasoline is crude plus a *crack spread* that wanders slowly
    around its own mean, so a crude move and a refining-margin move are
    different events with different persistence
  * the pump price adjusts gradually toward a cost anchor (the refined
    price + excise + VAT + margin), i.e. the two are cointegrated
  * adjustment is asymmetric: increases pass through faster than decreases
    ("rockets and feathers")
  * a mild weekly pattern and observation noise sit on top

The crude/crack split is not decoration. Until August 2026 this generator
made Brent an exact affine function of the gasoline series, which meant
crude carried no information the gasoline price did not already have --
and any feature built on it was untestable here by construction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import excise as excise_src

# Speed of pass-through per day, when the pump is *below* its cost anchor
# (wholesale rose, so prices rocket up) and when it is above (feathers down).
ADJUST_UP = 0.34
ADJUST_DOWN = 0.16

# Crude and the refining margin that sits on top of it, both in EUR per
# litre of finished product. They sum to roughly the 0.55 the wholesale
# series used to start at.
CRUDE_BASE = 0.43
CRACK_MEAN = 0.12
CRACK_PULL = 0.03  # per day, so a crack shock half-lives in ~3 weeks

_DOW_EFFECT = np.array([0.000, 0.001, 0.002, 0.004, 0.006, 0.004, 0.001])


def generate(
    start: str = "2015-01-01",
    end: str = "2026-08-01",
    seed: int = 20260806,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (pump_prices, market_prices) shaped like the real sources."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)

    # --- crude: random walk in logs, with occasional jumps --------------
    # The jumps are the supply scares -- a strait threatened, an OPEC cut.
    # They are what makes crude worth watching separately: a pump move
    # driven by one of these persists, because the barrel really did get
    # more expensive.
    shocks = rng.standard_normal(n) * 0.016
    jumps = (rng.random(n) < 0.012) * rng.standard_normal(n) * 0.06
    log_crude = np.log(CRUDE_BASE) + np.cumsum(shocks + jumps)
    crude = np.exp(log_crude).clip(0.20, 1.40)  # EUR/litre of crude in it

    # --- crack spread: refining margin, mean-reverting -------------------
    # A gasoline move that is only in the crack tends to unwind within
    # weeks. That is the distinction the crude features exist to make.
    crack = np.empty(n)
    crack[0] = CRACK_MEAN
    crack_noise = rng.standard_normal(n) * 0.004
    for t in range(1, n):
        crack[t] = crack[t - 1] + CRACK_PULL * (CRACK_MEAN - crack[t - 1]) + crack_noise[t]
    crack = crack.clip(0.02, 0.40)

    wholesale = crude + crack  # refined gasoline, EUR/litre ex-tax

    # --- cost anchor: what the pump "should" charge --------------------
    duty = excise_src.series(dates).to_numpy()
    vat = excise_src.vat_rate()
    gross_margin = 0.21  # retail + distribution margin, EUR/litre ex-VAT
    anchor = (wholesale + duty + gross_margin) * (1 + vat)

    # --- pump: asymmetric partial adjustment toward the anchor ---------
    pump = np.empty(n)
    pump[0] = anchor[0]
    for t in range(1, n):
        gap = anchor[t] - pump[t - 1]
        speed = ADJUST_UP if gap > 0 else ADJUST_DOWN
        pump[t] = pump[t - 1] + speed * gap

    pump = pump + _DOW_EFFECT[dates.dayofweek] + rng.standard_normal(n) * 0.004

    pump_df = pd.DataFrame({"date": dates, "euro95": np.round(pump, 3)})
    pump_df["available_from"] = pump_df["date"].map(_publication_date)

    # Market data only exists on trading days.
    market = pd.DataFrame(
        {
            "date": dates,
            "rbob_eur_l": np.round(wholesale, 4),
            "brent_eur_l": np.round(crude, 4),
            "eurusd": np.round(1.08 + np.cumsum(rng.standard_normal(n) * 0.002), 4),
        }
    )
    trading_day = ~market["date"].dt.dayofweek.isin([5, 6])
    market.loc[~trading_day, ["rbob_eur_l", "brent_eur_l", "eurusd"]] = np.nan
    market = market.ffill()

    return pump_df, market


def _publication_date(d: pd.Timestamp) -> pd.Timestamp:
    from .cbs import publication_date

    return publication_date(d)
