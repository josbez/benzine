"""Tests for the parts where a silent bug would be invisible in the output.

A forecaster fails quietly: a leak or an off-by-one in the publication lag
still produces plausible-looking prices, just with accuracy that evaporates
in production. These tests pin the timing rules down.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benzine.features import build_panel  # noqa: E402
from benzine.sources import excise, synthetic  # noqa: E402
from benzine.sources.cbs import publication_date  # noqa: E402


class TestPublicationLag:
    def test_monday_publishes_same_week_thursday(self):
        monday = pd.Timestamp("2026-03-02")
        assert monday.dayofweek == 0
        assert publication_date(monday) == pd.Timestamp("2026-03-05")

    def test_tuesday_waits_for_the_next_release(self):
        tuesday = pd.Timestamp("2026-03-03")
        assert publication_date(tuesday) == pd.Timestamp("2026-03-12")

    def test_sunday_publishes_with_the_following_monday(self):
        sunday = pd.Timestamp("2026-03-08")
        assert publication_date(sunday) == pd.Timestamp("2026-03-12")

    def test_never_available_before_it_happened(self):
        for day in pd.date_range("2026-01-01", "2026-12-31", freq="D"):
            assert publication_date(day) > day


class TestExcise:
    def test_rate_holds_until_the_next_change(self):
        dates = pd.DatetimeIndex(["2025-06-01", "2025-12-31", "2026-01-01"])
        rates = excise.series(dates)
        assert rates.iloc[0] == rates.iloc[1] == pytest.approx(0.789)
        assert rates.iloc[2] == pytest.approx(0.8447)

    def test_future_dates_carry_the_latest_known_rate(self):
        rate = excise.series(pd.DatetimeIndex(["2027-05-05"])).iloc[0]
        assert rate == pytest.approx(0.8447)


def pump_fixture() -> pd.DataFrame:
    pump, _ = synthetic.generate(start="2019-01-01", end="2024-12-31")
    return pump


class TestPanel:
    @pytest.fixture(scope="class")
    def panel(self):
        pump, market = synthetic.generate(start="2019-01-01", end="2024-12-31")
        return build_panel(pump, market)

    def test_anchor_is_never_from_the_future(self, panel):
        """The core no-leak guarantee: the anchor was published in the past."""
        assert (panel["anchor_date"] < panel["date"]).all()

    def test_anchor_respects_the_release_calendar(self, panel):
        published_at = panel["anchor_date"].map(publication_date)
        assert (published_at <= panel["date"]).all()

    def test_staleness_matches_the_publication_schedule(self, panel):
        # Between the same-week Thursday release and the next one, the
        # freshest available observation is 3 to 9 days old. The final rows
        # are excluded: the panel deliberately runs past the last published
        # price, so staleness keeps growing there -- that is the live case,
        # not a bug.
        settled = panel[panel["date"] <= panel["date"].max() - pd.Timedelta(days=14)]
        assert settled["staleness"].between(3, 9).all()

    def test_panel_extends_past_the_last_published_price(self, panel):
        """Forecast origins must reach 'today', not stop at the last release."""
        pump, _ = synthetic.generate(start="2019-01-01", end="2024-12-31")
        assert panel["date"].max() == pump["date"].max()
        # ...and the newest usable price is necessarily older than that.
        assert panel["anchor_date"].max() < panel["date"].max()

    def test_anchor_is_the_freshest_published_observation(self, panel):
        """Releases cover several days at once; we must take the newest of them."""
        row = panel.iloc[500]
        candidates = pump_fixture()
        available = candidates[candidates["available_from"] <= row["date"]]
        assert row["anchor_date"] == available["date"].max()

    def test_targets_line_up_with_the_actual_series(self, panel):
        row = panel.dropna(subset=["y_h3"]).iloc[100]
        assert row["actual_h3"] == pytest.approx(row["anchor"] + row["y_h3"])

    def test_no_target_columns_leak_into_features(self, panel):
        from benzine.features import feature_columns

        cols = feature_columns(panel, horizon=3)
        assert not [c for c in cols if c.startswith(("y_h", "actual_h"))]
        assert "duty_step_h3" in cols
        assert "duty_step_h5" not in cols


class TestAdvisoryAnchor:
    """The GLA path is what makes a *live* forecast current, so it needs
    the same no-leak guarantees as the CBS path."""

    @staticmethod
    def _inputs():
        pump, market = synthetic.generate(start="2021-01-01", end="2023-12-31")
        # A plausible advisory series: the pump price plus a list-price
        # premium, available same-day.
        gla = pump[["date", "euro95"]].copy()
        gla["gla_euro95"] = gla["euro95"] + 0.04
        return pump, market, gla[["date", "gla_euro95"]]

    def test_advisory_price_becomes_the_anchor(self):
        pump, market, gla = self._inputs()
        panel = build_panel(pump, market, gla)
        assert panel["anchor_is_gla"].mean() > 0.5
        assert panel["staleness"].max() <= 2

    def test_advisory_anchor_is_never_from_the_future(self):
        pump, market, gla = self._inputs()
        panel = build_panel(pump, market, gla)
        assert (panel["anchor_date"] <= panel["date"]).all()

    def test_list_price_premium_is_corrected_away(self):
        """The anchor should land on the CBS level, not 4 cents above it."""
        pump, market, gla = self._inputs()
        panel = build_panel(pump, market, gla)
        truth = pump.set_index("date")["euro95"]

        settled = panel[panel["anchor_is_gla"] == 1].tail(300)
        bias = (settled["anchor"].to_numpy()
                - truth.reindex(settled["anchor_date"]).to_numpy())
        assert abs(float(pd.Series(bias).mean())) < 0.01

    def test_offset_uses_only_past_overlaps(self):
        """Truncating the future must not change past anchors."""
        pump, market, gla = self._inputs()
        full = build_panel(pump, market, gla)
        cut = pd.Timestamp("2023-01-01")
        partial = build_panel(
            pump[pump["date"] <= cut], market, gla[gla["date"] <= cut]
        )

        # Only compare origins the truncated panel actually has data for;
        # past its own cut it necessarily coasts on a frozen anchor.
        merged = full.merge(partial, on="date", suffixes=("_full", "_cut"))
        merged = merged[merged["date"] <= cut - pd.Timedelta(days=10)]
        assert len(merged) > 100
        assert (merged["anchor_full"] - merged["anchor_cut"]).abs().max() < 1e-9


class TestModels:
    @pytest.fixture(scope="class")
    def panel(self):
        pump, market = synthetic.generate(start="2019-01-01", end="2024-12-31")
        return build_panel(pump, market)

    def test_quantiles_do_not_cross(self, panel):
        from benzine.model import QuantileForecaster

        train = panel.dropna(subset=["y_h2"])
        preds = QuantileForecaster(max_iter=40).fit(train, 2).predict(panel.tail(50))
        values = preds[["q10", "q25", "q50", "q75", "q90"]].to_numpy()
        assert (values[:, 1:] >= values[:, :-1]).all()

    def test_ecm_beats_the_naive_baseline_in_sample(self, panel):
        """A sanity check on the generator as much as the model: the
        synthetic process has real pass-through structure, so a model that
        cannot find it in-sample is broken."""
        from benzine.model import ECMForecaster

        train = panel.dropna(subset=["y_h2"])
        pred = ECMForecaster().fit(train, 2).predict(train)["q50"]
        mae = (pred - train["y_h2"]).abs().mean()
        mae_naive = train["y_h2"].abs().mean()
        assert mae < mae_naive


class TestBacktestTiming:
    def test_training_targets_are_published_before_the_refit(self):
        """The rule the whole backtest rests on."""
        from benzine.sources.cbs import publication_date as pub

        pump, market = synthetic.generate(start="2019-01-01", end="2023-12-31")
        panel = build_panel(pump, market)

        horizon = 3
        refit_at = pd.Timestamp("2022-06-01")
        target_known_at = (panel["date"] + pd.Timedelta(days=horizon)).map(pub)
        train = panel[target_known_at <= refit_at]

        latest_target = (train["date"] + pd.Timedelta(days=horizon)).max()
        assert pub(latest_target) <= refit_at
