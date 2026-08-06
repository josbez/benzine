"""Walk-forward evaluation with realistic information timing.

Two rules keep this honest, and both are easy to get wrong:

  1. A training row for horizon ``h`` originating on day ``s`` has its target
     on day ``s + h``, and that target is not *observable* until CBS
     publishes it. So at refit time ``t`` we may only train on rows where
     ``publication_date(s + h) <= t``. Training on targets that had not been
     published yet is the classic leak that makes a backtest sparkle.
  2. The model is refitted periodically on an expanding window, never fitted
     once on everything and evaluated in-sample.

Reported skill is relative to the naive random-walk forecast, because an
absolute MAE in cents means nothing without knowing how much the price
moved in the first place.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HORIZONS, QUANTILES
from .model import MODELS
from .sources.cbs import publication_date


@dataclass
class BacktestResult:
    predictions: pd.DataFrame
    metrics: pd.DataFrame

    def summary(self) -> str:
        cols = ["model", "horizon", "mae_cents", "rmse_cents", "skill_vs_naive",
                "coverage_80", "pinball"]
        view = self.metrics[cols].copy()
        for c in ("mae_cents", "rmse_cents"):
            view[c] = view[c].round(2)
        view["skill_vs_naive"] = (view["skill_vs_naive"] * 100).round(1)
        view["coverage_80"] = (view["coverage_80"] * 100).round(1)
        view["pinball"] = view["pinball"].round(4)
        return view.to_string(index=False)


def walk_forward(
    panel: pd.DataFrame,
    horizon: int,
    model_name: str = "gbm",
    initial_train_days: int = 730,
    refit_every: int = 30,
) -> pd.DataFrame:
    """Out-of-sample predictions for one model and horizon."""
    work = panel.copy()
    target_date = work["date"] + pd.Timedelta(days=horizon)
    work["target_known_at"] = target_date.map(publication_date)
    work = work.dropna(subset=[f"y_h{horizon}"]).reset_index(drop=True)

    start = work["date"].min() + pd.Timedelta(days=initial_train_days)
    test_origins = work[work["date"] >= start]
    if test_origins.empty:
        raise ValueError("not enough history for the requested training window")

    refit_dates = pd.date_range(
        test_origins["date"].min(), test_origins["date"].max(), freq=f"{refit_every}D"
    )

    chunks = []
    for i, refit_at in enumerate(refit_dates):
        block_end = (
            refit_dates[i + 1] if i + 1 < len(refit_dates) else test_origins["date"].max()
        )
        block = test_origins[
            (test_origins["date"] >= refit_at) & (test_origins["date"] < block_end)
        ]
        if i + 1 == len(refit_dates):
            block = test_origins[test_origins["date"] >= refit_at]
        if block.empty:
            continue

        train = work[work["target_known_at"] <= refit_at]
        if len(train) < 200:
            continue

        model = MODELS[model_name]().fit(train, horizon)
        preds = model.predict(block).set_index(block.index)

        out = block[["date", "anchor", f"y_h{horizon}", f"actual_h{horizon}"]].copy()
        out = out.join(preds)
        out["model"] = model_name
        out["horizon"] = horizon
        out["n_train"] = len(train)
        chunks.append(out)

    if not chunks:
        raise ValueError("no evaluable blocks; check the training window settings")

    result = pd.concat(chunks, ignore_index=True)
    return result.rename(columns={f"y_h{horizon}": "y_true",
                                  f"actual_h{horizon}": "actual"})


def evaluate(preds: pd.DataFrame) -> dict:
    """Point and probabilistic accuracy for one model/horizon block."""
    y = preds["y_true"].to_numpy()
    med = preds["q50"].to_numpy()

    err = med - y
    naive_err = -y  # the naive forecast is "no change"

    lo, hi = preds["q10"].to_numpy(), preds["q90"].to_numpy()
    coverage = float(np.mean((y >= lo) & (y <= hi)))

    pinball = float(
        np.mean(
            [
                _pinball(y, preds[f"q{int(q * 100):02d}"].to_numpy(), q)
                for q in QUANTILES
            ]
        )
    )

    mae = float(np.mean(np.abs(err)))
    mae_naive = float(np.mean(np.abs(naive_err)))
    return {
        "model": preds["model"].iloc[0],
        "horizon": int(preds["horizon"].iloc[0]),
        "n": len(preds),
        "mae_cents": mae * 100,
        "rmse_cents": float(np.sqrt(np.mean(err**2))) * 100,
        "mae_naive_cents": mae_naive * 100,
        "skill_vs_naive": 1 - mae / mae_naive if mae_naive else np.nan,
        "coverage_80": coverage,
        "pinball": pinball,
    }


def _pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    delta = y - pred
    return float(np.mean(np.maximum(q * delta, (q - 1) * delta)))


def run(
    panel: pd.DataFrame,
    models: tuple[str, ...] = ("naive", "ecm", "gbm"),
    horizons: tuple[int, ...] = HORIZONS,
    **kwargs,
) -> BacktestResult:
    all_preds, all_metrics = [], []
    for name in models:
        for h in horizons:
            preds = walk_forward(panel, h, model_name=name, **kwargs)
            all_preds.append(preds)
            all_metrics.append(evaluate(preds))
    return BacktestResult(
        predictions=pd.concat(all_preds, ignore_index=True),
        metrics=pd.DataFrame(all_metrics),
    )
