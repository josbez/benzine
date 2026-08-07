"""Turn raw sources into a modelling panel, one row per forecast origin.

Everything here is organised around a single rule: a row dated ``t`` may
only contain information that was actually knowable on day ``t``. That is
why the pump series is joined on ``available_from`` rather than ``date``.

The quantity we predict is deliberately not "the price on day t+h" but
"the change from the most recent price we know about to the price on day
t+h". Two things live inside that change:

  * the *nowcast* part -- CBS has not yet published the last few days, but
    the wholesale market already moved, so some of the change has happened
    and is merely unobserved;
  * the *forecast* part -- pass-through still in the pipeline.

Framing it this way makes the naive baseline exactly "no change", which is
the benchmark any forecaster has to beat to be worth running.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HORIZONS
from .sources import excise as excise_src

# Windows (in days) over which we measure wholesale moves.
_MARKET_WINDOWS = (1, 3, 7, 14)
# Lags of recent observed pump changes.
_PUMP_LAGS = (1, 2, 3, 5, 7)
# Overlapping days needed before the advisory price may anchor a forecast.
MIN_GLA_OVERLAP = 10


def build_panel(
    pump: pd.DataFrame,
    market: pd.DataFrame,
    gla: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = HORIZONS,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Assemble the feature/target panel.

    Args:
        pump: columns ``date``, ``euro95``, ``available_from``.
        market: columns ``date``, ``rbob_eur_l``, ``brent_eur_l``, ``eurusd``.
        gla: optional columns ``date``, ``gla_euro95`` -- same-day anchor.
        as_of: last forecast origin. Defaults to the newest date any source
            reaches, which is normally today -- deliberately *past* the last
            published pump price, because those recent origins are exactly
            the ones a live forecast runs from.
    """
    pump = pump.sort_values("date").reset_index(drop=True)
    market = market.sort_values("date").reset_index(drop=True)

    if as_of is None:
        as_of = max(pump["date"].max(), market["date"].max())
        if gla is not None and not gla.empty:
            as_of = max(as_of, gla["date"].max())
    dates = pd.date_range(pump["date"].min(), pd.Timestamp(as_of), freq="D")
    mk = _market_frame(market, dates)
    truth = pump.set_index("date")["euro95"].reindex(dates)

    panel = pd.DataFrame({"date": dates})
    panel = _attach_last_known(panel, pump)
    panel = panel.dropna(subset=["anchor"]).reset_index(drop=True)

    if gla is not None and not gla.empty:
        panel = _apply_gla_anchor(panel, gla)
    else:
        panel["anchor_is_gla"] = 0

    panel["staleness"] = (panel["date"] - panel["anchor_date"]).dt.days

    _add_market_features(panel, mk)
    _add_pump_history(panel, pump)
    _add_cost_gap(panel, mk)
    _add_calendar(panel)
    _add_targets(panel, truth, horizons)

    return _trim_to_usable(panel)


def _trim_to_usable(panel: pd.DataFrame) -> pd.DataFrame:
    """Drop the leading rows that predate the wholesale series.

    CBS pump prices start years before the free market feeds do, and a row
    with no wholesale price carries none of the signal this model runs on.
    Leaving those rows in is not merely wasteful: a training window landing
    entirely inside that era has every market feature missing at once,
    which is a far more confusing failure than a short panel.
    """
    usable = panel["margin"].notna()
    if not usable.any():
        raise ValueError(
            "no rows have wholesale prices -- the market series does not "
            "overlap the pump series at all"
        )
    return panel.loc[usable.idxmax() :].reset_index(drop=True)


# --------------------------------------------------------------------------
# anchors


def _attach_last_known(panel: pd.DataFrame, pump: pd.DataFrame) -> pd.DataFrame:
    """Join the most recent pump price that was published by each date."""
    # One release covers several observation days, so `available_from` has
    # ties. Sort on the observation date too: merge_asof takes the last row
    # of a tie group, and we want the freshest price in that release, not
    # whichever one an unstable sort happened to leave there.
    published = (
        pump[["available_from", "date", "euro95"]]
        .rename(columns={"date": "anchor_date", "euro95": "anchor"})
        .sort_values(["available_from", "anchor_date"], kind="mergesort")
    )
    return pd.merge_asof(
        panel.sort_values("date"),
        published,
        left_on="date",
        right_on="available_from",
        direction="backward",
    ).drop(columns=["available_from"])


def _apply_gla_anchor(panel: pd.DataFrame, gla: pd.DataFrame) -> pd.DataFrame:
    """Prefer the same-day advisory price when we have one.

    The GLA is a list price rather than a paid price, so it sits at a small
    offset from the CBS average. We shift it onto the CBS level before
    using it as an anchor.

    The offset is a trailing mean that is *shifted by one row*, so the
    correction applied on day t only ever uses overlaps observed before t.
    Estimating it once over the whole sample would be a lookahead leak --
    small in cents, but it would quietly flatter every backtest.
    """
    gla = gla.sort_values("date")
    merged = pd.merge_asof(
        panel.sort_values("date"),
        gla.rename(columns={"date": "gla_date"}),
        left_on="date",
        right_on="gla_date",
        direction="backward",
        tolerance=pd.Timedelta(days=2),
    )

    gap = merged["anchor"] - merged["gla_euro95"]
    offset = gap.shift(1).rolling(60, min_periods=MIN_GLA_OVERLAP).mean()

    # Until that offset is estimated, the advisory price is not usable as an
    # anchor at all. It is a list price from the five major brands, while CBS
    # is a volume-weighted average that includes unmanned discounters, so the
    # two sit cents apart. Adopting it uncorrected would visibly jump the
    # displayed price on the first day the scraper runs -- which is exactly
    # when nobody would recognise the jump as a bug.
    fresh = (
        merged["gla_euro95"].notna()
        & (merged["gla_date"] > merged["anchor_date"])
        & offset.notna()
    )
    merged["anchor_is_gla"] = fresh.astype(int)
    merged.loc[fresh, "anchor"] = merged.loc[fresh, "gla_euro95"] + offset[fresh]
    merged.loc[fresh, "anchor_date"] = merged.loc[fresh, "gla_date"]
    return merged.drop(columns=["gla_date", "gla_euro95"])


# --------------------------------------------------------------------------
# features


def _market_frame(market: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    mk = market.set_index("date").reindex(dates).ffill()
    mk.index.name = "date"
    return mk


def _add_market_features(panel: pd.DataFrame, mk: pd.DataFrame) -> None:
    """Wholesale moves, split into rises and falls.

    The split is the whole point: Dutch pump prices track wholesale
    increases far faster than decreases, so a single symmetric coefficient
    averages two genuinely different behaviours and fits neither.
    """
    rbob = mk["rbob_eur_l"]
    idx = panel["date"]

    for w in _MARKET_WINDOWS:
        change = (rbob - rbob.shift(w)).reindex(idx).to_numpy()
        panel[f"mkt_chg_{w}d"] = change
        panel[f"mkt_up_{w}d"] = np.clip(change, 0, None)
        panel[f"mkt_dn_{w}d"] = np.clip(change, None, 0)

    # Movement since the anchor observation: the part of the change that has
    # already happened in the world but is not yet in our anchor.
    rbob_at_anchor = rbob.reindex(panel["anchor_date"]).to_numpy()
    rbob_now = rbob.reindex(idx).to_numpy()
    unpriced = rbob_now - rbob_at_anchor
    panel["mkt_since_anchor"] = unpriced
    panel["mkt_since_anchor_up"] = np.clip(unpriced, 0, None)
    panel["mkt_since_anchor_dn"] = np.clip(unpriced, None, 0)

    vol = rbob.diff().rolling(20).std()
    panel["mkt_vol_20d"] = vol.reindex(idx).to_numpy()

    _add_crude_features(panel, mk)


def _add_crude_features(panel: pd.DataFrame, mk: pd.DataFrame) -> None:
    """Crude, and the refining margin between crude and gasoline.

    What is being forecast is a Dutch pump price, and crude never reaches
    a Dutch pump directly -- it reaches it through the refined product.
    So Brent enters here as a *driver* of the gasoline price, not as a
    second cost anchor: the cost base in `_add_cost_gap` stays the refined
    series, because that is what a Dutch retailer actually buys.

    What crude adds is the **crack spread**: whether a gasoline move will
    hold. A move that sits only in the crack is a refining-margin story
    and tends to unwind within weeks; a crude-driven move does not. Same
    size at the wholesale end, different pass-through at the pump.

    Only the crack, deliberately. Crude *changes* were tried too -- the
    same windows as the gasoline series, plus the move since the anchor --
    and they made the model worse: skill at five days fell from 14.1% to
    11.0% on five years of CBS data, degrading with horizon, which is what
    overfitting looks like. In hindsight that is the expected result.
    Crude and refined gasoline move together on almost every day, so those
    columns were near-duplicates of features the model already had, and
    the extra ways to fit noise cost more than the signal they added. The
    crack is the one piece that is genuinely orthogonal: it is the
    *difference* between the two series, which is exactly the part the
    gasoline price alone cannot tell you.

    No up/down split here, unlike the pump-side features: "rockets and
    feathers" is *retail* behaviour, and the crude-to-product leg is fast
    and close to symmetric.
    """
    brent = mk["brent_eur_l"]
    rbob = mk["rbob_eur_l"]
    idx = panel["date"]

    crack = (rbob - brent).reindex(idx)
    panel["crack"] = crack.to_numpy()
    panel["crack_dev"] = (
        crack - crack.rolling(90, min_periods=20).mean()
    ).to_numpy()


def _add_pump_history(panel: pd.DataFrame, pump: pd.DataFrame) -> None:
    """Recent observed pump momentum, measured back from the anchor date."""
    series = pump.set_index("date")["euro95"]
    full = series.reindex(
        pd.date_range(series.index.min(), series.index.max(), freq="D")
    ).ffill()
    anchor_dates = panel["anchor_date"]

    base = full.reindex(anchor_dates).to_numpy()
    for lag in _PUMP_LAGS:
        prior = full.reindex(anchor_dates - pd.Timedelta(days=lag)).to_numpy()
        panel[f"pump_chg_{lag}d"] = base - prior


def _add_cost_gap(panel: pd.DataFrame, mk: pd.DataFrame) -> None:
    """Error-correction term: how far the pump sits from its cost anchor.

    When the retail margin is unusually wide, competition pulls it back in;
    when it is unusually thin, prices catch up. This is the mean-reverting
    component that makes multi-day forecasting possible at all.
    """
    vat = excise_src.vat_rate()
    duty_now = excise_src.series(pd.DatetimeIndex(panel["date"])).to_numpy()
    rbob_now = mk["rbob_eur_l"].reindex(panel["date"]).to_numpy()

    implied = (rbob_now + duty_now) * (1 + vat)
    margin = panel["anchor"].to_numpy() - implied
    panel["margin"] = margin

    # Deviation of the margin from its own recent norm.
    margin_s = pd.Series(margin, index=panel["date"])
    panel["margin_dev"] = (margin_s - margin_s.rolling(90, min_periods=20).mean()).to_numpy()

    # Announced excise steps landing inside the forecast window are known
    # exactly, so they are handed to the model rather than inferred.
    for h in HORIZONS:
        future_duty = excise_src.series(
            pd.DatetimeIndex(panel["date"] + pd.Timedelta(days=h))
        ).to_numpy()
        panel[f"duty_step_h{h}"] = (future_duty - duty_now) * (1 + vat)


def _add_calendar(panel: pd.DataFrame) -> None:
    dow = panel["date"].dt.dayofweek
    panel["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    panel["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    panel["month_sin"] = np.sin(2 * np.pi * panel["date"].dt.month / 12)
    panel["month_cos"] = np.cos(2 * np.pi * panel["date"].dt.month / 12)


def _add_targets(panel: pd.DataFrame, truth: pd.Series, horizons) -> None:
    for h in horizons:
        future = truth.reindex(panel["date"] + pd.Timedelta(days=h)).to_numpy()
        panel[f"y_h{h}"] = future - panel["anchor"].to_numpy()
        panel[f"actual_h{h}"] = future


def feature_columns(panel: pd.DataFrame, horizon: int) -> list[str]:
    """Feature names for one horizon: shared columns plus that horizon's step."""
    drop_prefixes = ("y_h", "actual_h", "duty_step_h")
    cols = [
        c
        for c in panel.columns
        if c not in ("date", "anchor_date")
        and not c.startswith(drop_prefixes)
    ]
    return cols + [f"duty_step_h{horizon}"]
