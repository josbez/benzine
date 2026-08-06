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


def _qname(q: float) -> str:
    return f"q{int(q * 100):02d}"


class Forecaster:
    """Predicts the change from the anchor price, per quantile.

    Every model's intervals are conformalised before use. Quantile models
    fitted on history are reliably overconfident out of sample -- measured
    on real Dutch prices, a nominal 80% band covered 58-67% of outcomes,
    and that was true of the naive baseline's empirical quantiles too. The
    cause is not a modelling mistake so much as the shape of the series:
    fuel prices cluster their volatility, so an interval calibrated on the
    average of the past is too narrow whenever the present is choppy.

    The fix is split conformal prediction (CQR): hold out the most recent
    stretch of the training window, measure how far outside its own band
    each model actually lands there, and widen the band by that amount.
    This keeps whatever heteroscedasticity the quantile model found and
    corrects only the level -- and it applies to all three models, so the
    comparison between them stays fair.
    """

    quantiles: tuple[float, ...] = QUANTILES

    # Days of the training window reserved for calibration.
    CALIBRATION_DAYS = 365
    # Interval pairs to conformalise, as (lower, upper) quantiles.
    PAIRS = ((0.1, 0.9), (0.25, 0.75))
    # Below this, calibration is noisier than the miscalibration it fixes.
    MIN_CALIBRATION_ROWS = 120

    def fit(self, panel: pd.DataFrame, horizon: int) -> "Forecaster":
        target = f"y_h{horizon}"
        usable = panel.dropna(subset=[target])

        split = usable["date"].max() - pd.Timedelta(days=self.CALIBRATION_DAYS)
        core = usable[usable["date"] < split]
        calib = usable[usable["date"] >= split]

        if len(calib) < self.MIN_CALIBRATION_ROWS or len(core) < self.MIN_CALIBRATION_ROWS:
            # Not enough history to spare any; fit on everything and accept
            # uncalibrated intervals rather than fitting on a stub.
            self._fit_core(usable, horizon)
            self._widen = {}
            return self

        self._fit_core(core, horizon)
        self._widen = self._conformal_widths(calib, target)
        return self

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        return self._widen_frame(self._predict_raw(panel))

    # -- subclasses implement these ------------------------------------

    def _fit_core(self, panel: pd.DataFrame, horizon: int) -> None:
        raise NotImplementedError

    def _predict_raw(self, panel: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    # -- conformal calibration -----------------------------------------

    def _conformal_widths(self, calib: pd.DataFrame, target: str) -> dict:
        raw = self._predict_raw(calib)
        y = calib[target].to_numpy()

        widths = {}
        for lo, hi in self.PAIRS:
            if lo not in self.quantiles or hi not in self.quantiles:
                continue
            low = raw[_qname(lo)].to_numpy()
            high = raw[_qname(hi)].to_numpy()

            # How far outside its own interval each point landed.
            scores = np.maximum(low - y, y - high)

            alpha = lo + (1 - hi)
            n = len(scores)
            level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)

            # Widen only, never narrow. Textbook CQR allows a negative
            # correction, and on a genuinely exchangeable sample that is
            # correct. A price series is not exchangeable: volatility
            # clusters, so a calm calibration year followed by a choppy one
            # tells the model to tighten exactly when it should not. Tested
            # on synthetic data, allowing narrowing took coverage from 79%
            # down to 65%. We have measured undercoverage and never
            # overcoverage, so the correction is one-sided by design -- it
            # can only help against the failure we actually observe.
            widths[(lo, hi)] = max(0.0, float(np.quantile(scores, level)))
        return widths

    def _widen_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for (lo, hi), width in getattr(self, "_widen", {}).items():
            out[_qname(lo)] = out[_qname(lo)] - width
            out[_qname(hi)] = out[_qname(hi)] + width
        out[:] = np.sort(out.to_numpy(), axis=1)
        return out

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

    def _fit_core(self, panel: pd.DataFrame, horizon: int) -> None:
        y = panel[f"y_h{horizon}"].dropna().to_numpy()
        self._spread = {q: float(np.quantile(y, q)) for q in self.quantiles}

    def _predict_raw(self, panel: pd.DataFrame) -> pd.DataFrame:
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

    def _fit_core(self, panel: pd.DataFrame, horizon: int) -> None:
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

    def _predict_raw(self, panel: pd.DataFrame) -> pd.DataFrame:
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

    def _fit_core(self, panel: pd.DataFrame, horizon: int) -> None:
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

    def _predict_raw(self, panel: pd.DataFrame) -> pd.DataFrame:
        X = self._clean(panel[self.columns])
        return self._as_frame({q: m.predict(X) for q, m in self._models.items()})


MODELS = {
    "naive": NaiveForecaster,
    "ecm": ECMForecaster,
    "gbm": QuantileForecaster,
}
