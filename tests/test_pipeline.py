"""Tests for the parts where a silent bug would be invisible in the output.

A forecaster fails quietly: a leak or an off-by-one in the publication lag
still produces plausible-looking prices, just with accuracy that evaporates
in production. These tests pin the timing rules down.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benzine import pipeline  # noqa: E402
from benzine.features import build_panel  # noqa: E402
from benzine.sources import cache as cache_policy  # noqa: E402
from benzine.sources import cbs, excise, gla, market, synthetic  # noqa: E402
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


class TestShortMarketHistory:
    """The real feeds start years after CBS does.

    That mismatch crashed the first live backtest: an early training window
    fell entirely inside the era with no wholesale prices, every market
    feature was missing at once, and the model was handed an empty matrix.
    """

    @staticmethod
    def _inputs():
        pump, mkt = synthetic.generate(start="2015-01-01", end="2024-12-31")
        # Market data only from 2020 -- the shape of the live mismatch.
        return pump, mkt[mkt["date"] >= "2020-01-01"].reset_index(drop=True)

    def test_panel_starts_where_the_market_series_does(self):
        pump, mkt = self._inputs()
        panel = build_panel(pump, mkt)
        assert panel["date"].min() >= pd.Timestamp("2020-01-01")
        assert panel["margin"].notna().all()

    def test_ecm_fits_despite_missing_features(self):
        """Missing features must be imputed, never allowed to empty the set."""
        from benzine.model import ECMForecaster

        pump, mkt = self._inputs()
        panel = build_panel(pump, mkt)
        train = panel.copy()
        train["mkt_up_7d"] = float("nan")  # one column entirely absent

        model = ECMForecaster().fit(train, 2)
        assert model.predict(panel.tail(5))["q50"].notna().all()

    def test_fit_and_predict_agree_on_missing_values(self):
        """predict used to zero-fill what fit had dropped."""
        from benzine.model import ECMForecaster

        pump, mkt = self._inputs()
        panel = build_panel(pump, mkt)
        model = ECMForecaster().fit(panel, 2)

        complete = panel.dropna(subset=model.columns).tail(20)
        gapped = complete.copy()
        gapped.loc[gapped.index[0], "mkt_up_3d"] = float("nan")

        # A single gap should nudge one prediction, not shift the rest.
        base = model.predict(complete)["q50"].to_numpy()
        with_gap = model.predict(gapped)["q50"].to_numpy()
        assert (base[1:] == pytest.approx(with_gap[1:]))

    def test_test_years_bounds_what_is_scored_not_what_is_trained(self):
        """Limiting the window must shorten the evaluation, not the history
        each model gets to learn from."""
        from benzine import backtest as bt

        pump, mkt = self._inputs()
        panel = build_panel(pump, mkt)

        short = bt.walk_forward(panel, horizon=2, model_name="ecm",
                                refit_every=120, test_years=1.0)
        long = bt.walk_forward(panel, horizon=2, model_name="ecm",
                               refit_every=120, test_years=None)

        assert short["date"].min() > long["date"].min()
        assert short["date"].max() == long["date"].max()
        # The shorter window still trains on everything before it.
        assert short["n_train"].min() >= long["n_train"].min()

    def test_backtest_skips_windows_it_cannot_train_on(self):
        from benzine import backtest as bt

        pump, mkt = self._inputs()
        panel = build_panel(pump, mkt)
        preds = bt.walk_forward(panel, horizon=2, model_name="ecm",
                                initial_train_days=400, refit_every=120)
        assert len(preds) > 0
        assert preds["q50"].notna().all()


class TestConformalIntervals:
    """On real prices the nominal 80% band covered 58-67% of outcomes --
    for every model, the naive baseline included. These pin the fix."""

    @pytest.fixture(scope="class")
    def panel(self):
        pump, market = synthetic.generate(start="2016-01-01", end="2024-12-31")
        return build_panel(pump, market)

    @staticmethod
    def _coverage(model, frame, horizon):
        pred = model.predict(frame)
        y = frame[f"y_h{horizon}"].to_numpy()
        inside = (y >= pred["q10"].to_numpy()) & (y <= pred["q90"].to_numpy())
        return float(inside.mean())

    def test_calibration_holds_out_recent_data(self, panel):
        """The band must be measured on data the model did not fit."""
        from benzine.model import QuantileForecaster

        model = QuantileForecaster(max_iter=40).fit(panel, 2)
        assert model._widen, "no conformal widths were computed"

    def test_intervals_widen_when_the_model_is_overconfident(self, panel):
        """Squeeze a model's bands to a tenth and check calibration
        notices. The ECM is well calibrated on synthetic data, so proving
        the mechanism needs a model that is genuinely overconfident."""
        from benzine.model import ECMForecaster

        class Overconfident(ECMForecaster):
            def _predict_raw(self, frame):
                raw = super()._predict_raw(frame)
                centre = raw["q50"]
                return raw.apply(lambda col: centre + (col - centre) * 0.1)

        model = Overconfident().fit(panel, 2)
        assert model._widen[(0.1, 0.9)] > 0

        tail = panel.tail(200)
        raw_span = (model._predict_raw(tail)["q90"]
                    - model._predict_raw(tail)["q10"]).mean()
        adj = model.predict(tail)
        assert (adj["q90"] - adj["q10"]).mean() > raw_span

    def test_calibration_never_narrows(self, panel):
        """The correction is one-sided on purpose: allowing it to tighten
        took synthetic coverage from 79% to 65%."""
        from benzine.model import ECMForecaster, QuantileForecaster

        for model in (ECMForecaster().fit(panel, 2),
                      QuantileForecaster(max_iter=40).fit(panel, 2)):
            assert all(w >= 0 for w in model._widen.values())

    def test_calibrated_coverage_beats_uncalibrated(self, panel):
        """The whole point: closer to the 80% it claims."""
        from benzine.model import ECMForecaster

        train = panel[panel["date"] < "2023-01-01"]
        held_out = panel[panel["date"] >= "2023-01-01"].dropna(subset=["y_h2"])

        model = ECMForecaster().fit(train, 2)
        calibrated = self._coverage(model, held_out, 2)

        uncalibrated_model = ECMForecaster().fit(train, 2)
        uncalibrated_model._widen = {}
        uncalibrated = self._coverage(uncalibrated_model, held_out, 2)

        assert abs(calibrated - 0.80) <= abs(uncalibrated - 0.80)

    def test_short_history_skips_calibration_rather_than_fitting_a_stub(self):
        from benzine.model import ECMForecaster

        pump, market = synthetic.generate(start="2020-01-01", end="2020-09-30")
        small = build_panel(pump, market)
        model = ECMForecaster().fit(small, 2)
        assert model._widen == {}
        assert model.predict(small.tail(3))["q50"].notna().all()


class TestMarketProviders:
    """Free market feeds answer fine from a laptop and return block pages
    from cloud runners, so the fallback path is the one that matters."""

    @staticmethod
    def _series(n=3):
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        return pd.Series(range(n), index=idx, dtype=float)

    @pytest.fixture(autouse=True)
    def _no_waiting(self, monkeypatch):
        """Record the backoff instead of sleeping through it."""
        self.slept = []
        monkeypatch.setattr(market.time, "sleep", self.slept.append)

    def test_falls_back_when_the_first_provider_fails(self, monkeypatch):
        monkeypatch.setattr(
            market, "_yahoo",
            lambda s, w=None: (_ for _ in ()).throw(RuntimeError("blocked")),
        )
        monkeypatch.setattr(market, "_stooq", lambda s, w=None: self._series())
        assert len(market._first_working("rbob", "RB=F", "rb.f")) == 3

    def test_falls_back_when_the_first_provider_returns_nothing(self, monkeypatch):
        """An empty series is a failure, not a valid answer."""
        monkeypatch.setattr(market, "_yahoo", lambda s, w=None: pd.Series(dtype=float))
        monkeypatch.setattr(market, "_stooq", lambda s, w=None: self._series())
        assert len(market._first_working("rbob", "RB=F", "rb.f")) == 3

    def test_retries_a_provider_before_giving_up_on_it(self, monkeypatch):
        """One timeout used to cost a red run -- and, through the daily job,
        a permanently lost day of advisory-price history."""
        calls = []

        def flaky(symbol, window=None):
            calls.append(symbol)
            if len(calls) < 2:
                raise RuntimeError("connection reset")
            return self._series()

        monkeypatch.setattr(market, "_yahoo", flaky)
        monkeypatch.setattr(
            market, "_stooq",
            lambda s, w=None: (_ for _ in ()).throw(AssertionError("never reached")),
        )
        assert len(market._first_working("rbob", "RB=F", "rb.f")) == 3
        assert len(calls) == 2
        assert len(self.slept) == 1

    def test_backoff_grows_between_attempts(self, monkeypatch):
        monkeypatch.setattr(
            market, "_yahoo",
            lambda s, w=None: (_ for _ in ()).throw(RuntimeError("down")),
        )
        monkeypatch.setattr(market, "_stooq", lambda s, w=None: self._series())
        market._first_working("rbob", "RB=F", "rb.f")
        assert len(self.slept) == market._ATTEMPTS - 1
        assert self.slept[1] > self.slept[0]

    def test_an_empty_answer_moves_on_instead_of_retrying(self, monkeypatch):
        """A blocked symbol answers empty every time; retrying only delays
        the handover to the provider that would have worked."""
        calls = []
        monkeypatch.setattr(
            market, "_yahoo",
            lambda s, w=None: (calls.append(s), pd.Series(dtype=float))[1],
        )
        monkeypatch.setattr(market, "_stooq", lambda s, w=None: self._series())
        market._first_working("rbob", "RB=F", "rb.f")
        assert len(calls) == 1
        assert self.slept == []

    def test_reports_every_attempt_when_all_fail(self, monkeypatch):
        """The error has to name both providers, or diagnosing it from a CI
        log means guessing which one was even tried."""
        monkeypatch.setattr(
            market, "_yahoo",
            lambda s, w=None: (_ for _ in ()).throw(RuntimeError("yahoo down")),
        )
        monkeypatch.setattr(
            market, "_stooq",
            lambda s, w=None: (_ for _ in ()).throw(RuntimeError("got HTML")),
        )
        with pytest.raises(RuntimeError) as err:
            market._first_working("rbob", "RB=F", "rb.f")
        assert "yahoo down" in str(err.value)
        assert "got HTML" in str(err.value)

    def test_stooq_rejects_an_html_block_page(self, monkeypatch):
        """The exact failure seen from GitHub's runners: HTML, not CSV,
        served with a 200 so raise_for_status does not catch it."""
        monkeypatch.setattr(
            market.requests, "get",
            lambda *a, **k: _FakeResponse("<meta charset=utf-8><title>Stooq</title>"),
        )
        with pytest.raises(RuntimeError, match="expected CSV"):
            market._stooq("cb.f")

    def test_stooq_accepts_real_csv(self, monkeypatch):
        csv = "Date,Open,High,Low,Close,Volume\n2026-01-02,2.0,2.1,1.9,2.05,10\n"
        monkeypatch.setattr(
            market.requests, "get", lambda *a, **k: _FakeResponse(csv)
        )
        assert market._stooq("cb.f").iloc[0] == pytest.approx(2.05)


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class TestMarketCache:
    """The daily job used to re-download twenty years of history every
    morning. It now asks for a window and lays it over what it has."""

    @staticmethod
    def _cached(start="2020-01-01", periods=5) -> pd.DataFrame:
        idx = pd.date_range(start, periods=periods, freq="D")
        return pd.DataFrame(
            {
                "date": idx,
                "rbob": 2.0,
                "brent": 80.0,
                "eurusd": 1.1,
                "rbob_eur_l": 0.48,
                "brent_eur_l": 0.46,
            }
        )

    @staticmethod
    def _window(start, periods=3, value=3.0) -> pd.DataFrame:
        idx = pd.date_range(start, periods=periods, freq="D")
        return pd.DataFrame(
            {"rbob": value, "brent": 90.0, "eurusd": 1.2}, index=idx
        )

    def test_keeps_history_the_window_no_longer_covers(self):
        """The whole point of the cache: 2006 is not in a 6-month window,
        and throwing it away would throw away the training data with it."""
        spliced = market._splice(self._cached(), self._window("2020-01-04"))
        assert spliced.index.min() == pd.Timestamp("2020-01-01")
        assert spliced.index.max() == pd.Timestamp("2020-01-06")

    def test_fresh_rows_win_on_overlapping_dates(self):
        """Providers revise a close after the fact; the window is fetched
        precisely to pick that up."""
        spliced = market._splice(self._cached(), self._window("2020-01-04"))
        assert spliced.loc["2020-01-04", "rbob"] == pytest.approx(3.0)
        assert spliced.loc["2020-01-01", "rbob"] == pytest.approx(2.0)

    def test_no_cache_means_the_full_history(self):
        assert len(market._splice(None, self._window("2020-01-01"))) == 3

    def test_second_fetch_tops_up_instead_of_re_downloading(
        self, tmp_path, monkeypatch
    ):
        """The wiring, not just the splice: the first call takes the full
        history, a later one asks for a window and keeps what it had."""
        monkeypatch.setattr(market, "RAW", tmp_path)
        windows = []

        def provider(symbol, window=None):
            windows.append(window)
            end = "2020-06-30" if window == market._FULL_RANGE else "2020-07-31"
            idx = pd.date_range("2020-01-01", end, freq="D")
            return pd.Series(2.0, index=idx)

        monkeypatch.setattr(market, "_yahoo", provider)

        first = market.fetch()
        assert set(windows) == {market._FULL_RANGE}
        assert first["date"].max() == pd.Timestamp("2020-06-30")

        # Age the cache past its expiry so the next call actually refetches.
        import os

        stale = dt.datetime.now() - dt.timedelta(days=1)
        os.utime(tmp_path / "market.parquet", (stale.timestamp(), stale.timestamp()))

        windows.clear()
        second = market.fetch()
        assert set(windows) == {market._TOPUP_RANGE}
        assert second["date"].min() == pd.Timestamp("2020-01-01")
        assert second["date"].max() == pd.Timestamp("2020-07-31")

    def test_a_fresh_cache_is_served_without_a_request(self, tmp_path, monkeypatch):
        monkeypatch.setattr(market, "RAW", tmp_path)
        self._cached().to_parquet(tmp_path / "market.parquet", index=False)
        monkeypatch.setattr(
            market, "_yahoo",
            lambda s, w=None: (_ for _ in ()).throw(AssertionError("no request")),
        )
        monkeypatch.setattr(
            market, "_stooq",
            lambda s, w=None: (_ for _ in ()).throw(AssertionError("no request")),
        )
        assert len(market.fetch()) == 5

    def test_weekends_are_filled_and_converted(self):
        idx = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])  # Friday, Monday
        raw = pd.DataFrame({"rbob": 2.0, "brent": 80.0, "eurusd": 1.0}, index=idx)
        out = market._derive(raw)
        assert len(out) == 4  # the weekend is carried forward
        assert out["rbob_eur_l"].iloc[0] == pytest.approx(2.0 / 3.785411784)


class TestCacheFreshness:
    """A cache with no expiry is not a cache but a snapshot: without this
    check a local run keeps using whatever prices it first downloaded."""

    def test_a_missing_file_is_never_fresh(self, tmp_path):
        assert not cache_policy.is_fresh(tmp_path / "absent.parquet")

    def test_a_file_just_written_is_fresh(self, tmp_path):
        path = tmp_path / "market.parquet"
        path.write_text("x")
        assert cache_policy.is_fresh(path)

    def test_an_old_file_is_not(self, tmp_path):
        import os

        path = tmp_path / "market.parquet"
        path.write_text("x")
        stale = dt.datetime.now() - dt.timedelta(days=3)
        os.utime(path, (stale.timestamp(), stale.timestamp()))
        assert not cache_policy.is_fresh(path)


class TestCbsCacheFallback:
    """A CBS outage should cost freshness, not correctness -- but only for
    as long as the cache still represents the latest release."""

    @staticmethod
    def _cache(tmp_path, monkeypatch, age: dt.timedelta):
        import os

        monkeypatch.setattr(cbs, "RAW", tmp_path)
        path = tmp_path / f"cbs_{cbs.CBS_TABLE}.parquet"
        pump, _ = synthetic.generate(start="2024-01-01", end="2024-03-01")
        pump.to_parquet(path, index=False)
        written = dt.datetime.now() - age
        os.utime(path, (written.timestamp(), written.timestamp()))
        monkeypatch.setattr(
            cbs, "_download",
            lambda: (_ for _ in ()).throw(RuntimeError("CBS unreachable")),
        )
        return path

    def test_a_recent_cache_absorbs_an_outage(self, tmp_path, monkeypatch, capsys):
        self._cache(tmp_path, monkeypatch, dt.timedelta(days=2))
        assert not cbs.fetch().empty
        assert "CBS refresh failed" in capsys.readouterr().out

    def test_an_old_cache_does_not(self, tmp_path, monkeypatch):
        """Past a release cycle the cache is missing a publication, and
        pretending otherwise is worse than a red run."""
        self._cache(tmp_path, monkeypatch, dt.timedelta(days=30))
        with pytest.raises(RuntimeError, match="CBS unreachable"):
            cbs.fetch()

    def test_no_cache_at_all_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cbs, "RAW", tmp_path)
        monkeypatch.setattr(
            cbs, "_download",
            lambda: (_ for _ in ()).throw(RuntimeError("CBS unreachable")),
        )
        with pytest.raises(RuntimeError, match="CBS unreachable"):
            cbs.fetch()


class TestDegradedInputs:
    """Optional inputs must degrade, not detonate: an unreadable extra
    should never be able to stop a forecast that has everything it needs."""

    def test_a_corrupt_advisory_history_still_yields_a_forecast(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            pipeline.gla, "load",
            lambda: (_ for _ in ()).throw(ValueError("bad line 3")),
        )
        pump, mkt, advisory, resolved = pipeline.load_inputs("synthetic")
        assert advisory.empty
        assert resolved == "synthetic"
        assert not build_panel(pump, mkt, advisory).empty
        assert "advisory-price history unreadable" in capsys.readouterr().out


class TestAdvisoryScraper:
    """The live page cannot be reached from CI-less environments, so these
    pin the parsing rules against markup shaped like the real thing."""

    PAGE = """
    <html><head><style>.p { color: red }</style>
    <script>var lastPrice = "9,999";</script></head>
    <body>
      <nav><a href="/tanken/benzine">Benzine</a><a href="/tanken/diesel">Diesel</a></nav>
      <h1>Gemiddelde landelijke adviesprijs</h1>
      <table>
        <tr><th>Brandstof</th><th>Prijs</th></tr>
        <tr><td>Euro 95 (E10)</td><td>&euro;&nbsp;2,109</td></tr>
        <tr><td>Diesel</td><td>&euro;&nbsp;1,879</td></tr>
        <tr><td>LPG</td><td>&euro;&nbsp;0,999</td></tr>
      </table>
    </body></html>
    """

    def test_reads_the_euro95_price(self):
        assert gla.scrape(self.PAGE) == pytest.approx(2.109)

    def test_ignores_navigation_mentions_of_benzine(self):
        """A menu link says "Benzine" long before the table does."""
        assert gla.scrape(self.PAGE) != pytest.approx(1.879)

    def test_ignores_prices_hidden_in_scripts(self):
        assert "9,999" not in gla.to_text(self.PAGE)

    def test_rejects_implausible_values(self):
        assert gla.find_price("Euro 95 kost 9,99 per liter") is None

    def test_error_shows_what_the_page_contained(self):
        """Diagnosing a scrape failure from a log needs the page text."""
        with pytest.raises(RuntimeError, match="Koekjes"):
            gla.scrape("<html><body><h1>Koekjes accepteren</h1></body></html>")


class TestPriceProbe:
    """On 7 August 2026 the live page had no price and no fuel label in its
    text at all. `diagnose()` says *that*; these pin down the tooling that
    says *where the price went instead*."""

    NEXT_PAGE = """
    <html><head><title>Adviesprijs</title></head><body>
      <div id="root"></div>
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"fuels":[
          {"name":"Euro 95 (E10)","adviesprijs":2.109},
          {"name":"Diesel","adviesprijs":1.879}]}}}
      </script>
      <script>window.__CONFIG__ = {"apiBase":"/api/v2/brandstofprijzen"};</script>
    </body></html>
    """

    def test_finds_a_price_the_text_parser_cannot_see(self):
        """The decisive case: `to_text()` strips <script>, so a Next.js
        payload is invisible to both find_price and diagnose -- yet the
        price is sitting right there in the HTML."""
        assert gla.find_price(gla.to_text(self.NEXT_PAGE)) is None
        report = gla.probe(self.NEXT_PAGE)
        assert "2.109" in report
        assert "the price is in the HTML after all" in report

    def test_names_the_blob_that_holds_it(self):
        """Without the script's id, the report says a price exists
        somewhere and leaves you to find it."""
        report = gla.probe(self.NEXT_PAGE)
        assert "__NEXT_DATA__" in report
        assert "adviesprijs" in report

    def test_parses_an_assignment_not_just_a_bare_payload(self):
        blobs = dict(gla.embedded_json(self.NEXT_PAGE))
        assert "<inline>" in blobs
        assert blobs["<inline>"]["apiBase"] == "/api/v2/brandstofprijzen"

    def test_lists_candidate_endpoints(self):
        assert "/api/v2/brandstofprijzen" in gla.find_endpoints(self.NEXT_PAGE)

    def test_ignores_assets(self):
        """Every page links dozens of scripts and none of them are data."""
        html = '<script src="/_next/static/chunks/api-4f2.js"></script>'
        assert gla.find_endpoints(html) == []

    def test_rejects_numbers_that_are_not_prices(self):
        """A page is full of small numbers -- ids, counts, ratings."""
        assert not gla._price_like(0.5)
        assert not gla._price_like(2026)
        assert not gla._price_like(True)
        assert gla._price_like(2.109)
        assert gla._price_like("2,109")

    def test_says_so_when_there_is_no_json_at_all(self):
        report = gla.probe("<html><body><p>Niets hier</p></body></html>")
        assert "no parseable JSON" in report


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
        # Once it takes over, the anchor is same-day rather than days stale.
        # Earlier rows still sit on CBS while the offset is being estimated.
        assert panel.loc[panel["anchor_is_gla"] == 1, "staleness"].max() <= 2

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

    def test_short_history_does_not_anchor_on_the_list_price(self):
        """Day one of the scraper must not jump the displayed price.

        The advisory price sits cents above the CBS average, so before the
        offset is estimated the anchor has to stay on CBS.
        """
        from benzine.features import MIN_GLA_OVERLAP

        pump, market, full_gla = self._inputs()
        short = full_gla.tail(MIN_GLA_OVERLAP - 1)
        panel = build_panel(pump, market, short)
        assert panel["anchor_is_gla"].sum() == 0

        truth = pump.set_index("date")["euro95"]
        tail = panel.tail(5)
        bias = (tail["anchor"].to_numpy()
                - truth.reindex(tail["anchor_date"]).to_numpy())
        assert abs(float(pd.Series(bias).mean())) < 1e-9

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
