"""End-to-end: load sources, build the panel, backtest, publish a forecast."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .config import HORIZONS, METRICS_FILE, PROCESSED, WEB
from .features import build_panel
from .model import MODELS
from .sources import cbs, gla, market, synthetic

HISTORY_DAYS = 120


def save_metrics(metrics: pd.DataFrame) -> None:
    METRICS_FILE.write_text(metrics.round(4).to_json(orient="records", indent=2))


def load_metrics() -> pd.DataFrame | None:
    """Backtest scores from the last evaluation run, if there is one."""
    if not METRICS_FILE.exists():
        return None
    try:
        return pd.read_json(METRICS_FILE)
    except ValueError:
        return None


def load_inputs(source: str = "auto") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """Fetch pump, market and advisory-price data.

    ``auto`` tries the live feeds and falls back to the synthetic generator
    if they are unreachable, so development never blocks on network access.
    The chosen source is returned and propagated all the way to the UI --
    a forecast built on synthetic data must never be presented as real.
    """
    if source == "synthetic":
        pump, mkt = synthetic.generate()
        return pump, mkt, gla.load(), "synthetic"

    try:
        pump = cbs.fetch()
        mkt = market.fetch()
        return pump, mkt, gla.load(), "live"
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        if source == "live":
            raise
        print(f"  live sources unavailable ({type(exc).__name__}: {exc})")
        print("  falling back to synthetic data")
        pump, mkt = synthetic.generate()
        return pump, mkt, gla.load(), "synthetic"


def build(source: str = "auto") -> tuple[pd.DataFrame, pd.DataFrame, str]:
    pump, mkt, advisory, resolved = load_inputs(source)
    panel = build_panel(pump, mkt, advisory)
    panel.to_parquet(PROCESSED / "panel.parquet", index=False)
    return panel, pump, resolved


def publish_forecast(
    panel: pd.DataFrame,
    pump: pd.DataFrame,
    metrics: pd.DataFrame | None = None,
    model_name: str = "gbm",
    data_source: str = "synthetic",
    horizons: tuple[int, ...] = HORIZONS,
) -> dict:
    """Fit on all available history and write web/forecast.json."""
    if metrics is None:
        metrics = load_metrics()

    latest = panel.iloc[-1]
    anchor = float(latest["anchor"])
    origin = pd.Timestamp(latest["date"])

    rows = []
    for h in horizons:
        train = panel.dropna(subset=[f"y_h{h}"])
        model = MODELS[model_name]().fit(train, h)
        pred = model.predict(panel.tail(1)).iloc[0]
        rows.append(
            {
                "date": (origin + pd.Timedelta(days=h)).date().isoformat(),
                "horizon": h,
                **{k: round(anchor + float(v), 4) for k, v in pred.items()},
            }
        )

    # History is the measured series by observation date -- not the anchor
    # column, which is a step function because it only refreshes when CBS
    # publishes. The line therefore stops at the last published day and the
    # fan carries on from there, which is an honest picture of what is known.
    history = (
        pump[pump["available_from"] <= origin][["date", "euro95"]]
        .tail(HISTORY_DAYS)
        .assign(date=lambda d: d["date"].dt.date.astype(str))
        .rename(columns={"euro95": "price"})
        .round({"price": 4})
        .to_dict("records")
    )

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fuel": "Euro 95 (E10)",
        "data_source": data_source,
        "anchor": {
            "date": pd.Timestamp(latest["anchor_date"]).date().isoformat(),
            "price": round(anchor, 4),
            "source": "adviesprijs" if latest.get("anchor_is_gla") else "CBS",
            "staleness_days": int(latest["staleness"]),
        },
        "history": history,
        "forecast": rows,
        "model": model_name,
        "backtest": (
            metrics[metrics["model"] == model_name].round(4).to_dict("records")
            if metrics is not None and not metrics.empty
            else []
        ),
    }

    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "forecast.json").write_text(json.dumps(payload, indent=2))
    return payload
