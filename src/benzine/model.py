"""Forecasting models.

Three of them, deliberately:

  * `NaiveForecaster` -- tomorrow's price is today's price. Petrol prices are
    close to a random walk, so this is a genuinely strong benchmark. Any
    model that cannot beat it is not worth deploying.
  * `ECMForecaster` -- a linear error-correction model with asymmetric
    pass-through. Interpretable, hard to overfit, and usually within a
    whisker of the gradient booster.
  * `QuantileForecaster` -- gradient-boosted quantile regression, which
    gives the fan chart the UI needs rather than a single misleading line.

All three share the same interface so the backtest can treat them alike.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import QUANTILES
from .features import feature_columns


class Forecaster:
    """Predicts the change from the anchor price, per quantile."""

    quantiles: tuple[float, ...] = QUANTILES

    def fit(self, panel: pd.DataFrame, horizon: int) -> "Forecaster":
        raise NotImplementedError

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @staticmethod
    def _clean(frame: pd.DataFrame) -> np.ndarray:
        return frame.to_numpy(dtype=float)

    def _as_frame(self, columns: dict[float, np.ndarray]) -> pd.DataFrame:
        out = pd.DataFrame({f"q{int(q * 100):02d}": v for q, v in columns.items()})
        # Quantile models are fitted independently and can cross; sorting
        # each row restores a valid distribution.
        out[:] = np.sort(out.to_numpy(), axis=1)
        return out


class NaiveForecaster(Forecaster):
    """No change from the anchor, with uncertainty from historical spread."""

    def __init__(self) -> None:
        self._spread: dict[float, float] = {}

    def fit(self, panel: pd.DataFrame, horizon: int) -> "NaiveForecaster":
        y = panel[f"y_h{horizon}"].dropna().to_numpy()
        self._spread = {q: float(np.quantile(y, q)) for q in self.quantiles}
        return self

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        n = len(panel)
        return self._as_frame({q: np.full(n, v) for q, v in self._spread.items()})


@dataclass
class ECMForecaster(Forecaster):
    """Linear error correction with rockets-and-feathers asymmetry."""

    alpha: float = 1.0
    columns: list[str] = field(default_factory=list)
    _model: object = None
    _resid_q: dict[float, float] = field(default_factory=dict)

    KEY_FEATURES = (
        "margin_dev",
        "staleness",
        "mkt_since_anchor_up",
        "mkt_since_anchor_dn",
        "mkt_up_3d",
        "mkt_dn_3d",
        "mkt_up_7d",
        "mkt_dn_7d",
        "pump_chg_3d",
        "dow_sin",
        "dow_cos",
    )

    def fit(self, panel: pd.DataFrame, horizon: int) -> "ECMForecaster":
        self.columns = [c for c in self.KEY_FEATURES if c in panel.columns]
        self.columns.append(f"duty_step_h{horizon}")

        # Drop rows with no target, but impute missing *features* rather
        # than dropping them. Dropping was both fragile and inconsistent:
        # a single all-NaN feature column emptied the training set (which
        # is exactly what happens early in the sample, before the market
        # series begins), while predict filled the same gaps with zero. Fit
        # and predict have to treat missing values identically.
        frame = panel[self.columns + [f"y_h{horizon}"]].dropna(
            subset=[f"y_h{horizon}"]
        )
        X = self._clean(frame[self.columns])
        y = frame[f"y_h{horizon}"].to_numpy()

        self._model = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            StandardScaler(),
            Ridge(alpha=self.alpha),
        ).fit(X, y)
        resid = y - self._model.predict(X)
        self._resid_q = {q: float(np.quantile(resid, q)) for q in self.quantiles}
        return self

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        X = self._clean(panel[self.columns])  # the pipeline imputes
        centre = self._model.predict(X)
        return self._as_frame({q: centre + off for q, off in self._resid_q.items()})


class QuantileForecaster(Forecaster):
    """Gradient-boosted quantile regression, one model per quantile."""

    def __init__(self, max_iter: int = 250, learning_rate: float = 0.05,
                 max_depth: int = 4, min_samples_leaf: int = 40) -> None:
        self.params = dict(
            max_iter=max_iter,
            learning_rate=learning_rate,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            l2_regularization=1.0,
            early_stopping=False,
        )
        self.columns: list[str] = []
        self._models: dict[float, HistGradientBoostingRegressor] = {}

    def fit(self, panel: pd.DataFrame, horizon: int) -> "QuantileForecaster":
        self.columns = feature_columns(panel, horizon)
        frame = panel[self.columns + [f"y_h{horizon}"]].dropna(
            subset=[f"y_h{horizon}"]
        )
        X = self._clean(frame[self.columns])
        y = frame[f"y_h{horizon}"].to_numpy()

        for q in self.quantiles:
            model = HistGradientBoostingRegressor(
                loss="quantile", quantile=q, **self.params
            )
            self._models[q] = model.fit(X, y)
        return self

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        X = self._clean(panel[self.columns])
        return self._as_frame({q: m.predict(X) for q, m in self._models.items()})


MODELS = {
    "naive": NaiveForecaster,
    "ecm": ECMForecaster,
    "gbm": QuantileForecaster,
}
