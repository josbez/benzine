# Benzineprijs forecaster

A 1–5 day ahead forecast for the Dutch average Euro 95 pump price, with a
mobile-first web front end.

## Why this can work at all

The honest version: the underlying market price is not forecastable. Brent
and the Rotterdam gasoline barge (EBOB) assessment behave like random walks,
and anyone who could predict tomorrow's oil price would not be shipping a
web app.

What *is* forecastable is the lag between the wholesale market and the pump:

```
Brent + EUR/USD  →  EBOB Rotterdam  →  advisory price  →  pump price
     (day 0)            (day 0)         (day +1..+5)      (day +2..+14)
```

A wholesale move that happened today is still working its way to the pump a
week later. Forecasting that is not prediction so much as bookkeeping on
information that already exists. Three things make it tractable:

- **Pass-through lag.** Most of a 1–5 day forecast is already-observed
  wholesale movement that has not reached the pump yet.
- **Rockets and feathers.** Increases pass through faster than decreases —
  a well-documented asymmetry in retail fuel markets. The model fits
  separate coefficients for rises and falls instead of averaging two
  different behaviours into one.
- **Excise duty is known in advance.** Announced accijns changes are exact,
  deterministic jumps. They are handed to the model as a known future step
  (`data/excise.yaml`) rather than something it has to infer.

Past ~5 days the pipeline has drained and you are forecasting the oil market
itself, so the horizon deliberately stops there.

## Quick start

```bash
make install
make demo     # offline, synthetic data — verifies the pipeline end to end
make serve    # http://localhost:8000
```

For real forecasts:

```bash
make all      # fetches CBS + market data, backtests, writes web/forecast.json
```

## The timing problem, and why it dominates the design

CBS publishes daily pump prices **on Thursday, covering days through that
week's Monday**. A Tuesday price is therefore not public until nine days
later. This matters more than the choice of model:

- CBS is the **training label**, not a live input. Building features from
  CBS prices as if they were available same-day produces a backtest that
  looks superb and a deployment that does not work.
- The **live anchor** is the UnitedConsumers *gemiddelde landelijke
  adviesprijs* (GLA), which is published daily. There is no public archive,
  so `make snapshot` appends today's value to `data/raw/gla_history.csv` —
  run it from cron and the history accumulates.

Every row of the modelling panel is stamped with what was knowable on that
date (`features.py`), and the backtest only trains on targets that had
already been *published* at each refit (`backtest.py`). Tests pin both rules
down; `test_anchor_is_never_from_the_future` and
`test_training_targets_are_published_before_the_refit` are the ones that
matter.

Because of the lag, part of every forecast is really a **nowcast**: filling
in days that have already happened but are not yet published. The UI says so
rather than pretending the anchor is today's price.

## What it predicts

Not the price level, but the **change from the most recent known price**.
That makes the naive baseline exactly "no change" — a genuinely strong
benchmark for a near-random-walk series, and the only fair thing to measure
against. Reported skill is the reduction in MAE relative to it.

Output is a set of quantiles (10/25/50/75/90), not a single line, so the app
can show a widening band instead of implying false precision.

## Data sources

| Source | What | Role |
|---|---|---|
| [CBS 80416ned](https://www.cbs.nl/nl-nl/cijfers/detail/80416ned) | daily national average pump price | training label |
| [UnitedConsumers GLA](https://www.unitedconsumers.com/tanken/info/gemiddelde-landelijke-adviesprijs) | daily advisory price | live anchor |
| Stooq (RBOB, Brent, EUR/USD) | wholesale market | leading indicator |
| `data/excise.yaml` | accijns schedule | known future steps |

RBOB stands in for the real EBOB Rotterdam assessment, which is a paid
Argus/Platts product. Swapping in a licensed EBOB feed means changing
`sources/market.py` and nothing else.

## Models

| Model | What it is |
|---|---|
| `naive` | no change from the anchor — the benchmark |
| `ecm` | linear error-correction with asymmetric pass-through; interpretable and hard to overfit |
| `gbm` | gradient-boosted quantile regression; produces the fan chart |

The error-correction term is the important feature: when the retail margin
sits above its recent norm, competition pulls it back down, and vice versa.
That mean reversion is what makes multi-day forecasting possible at all.

## Layout

```
src/benzine/
  sources/       CBS, market, GLA, excise, synthetic fallback
  features.py    the panel — every row limited to what was knowable that day
  model.py       naive / ECM / quantile GBM
  backtest.py    walk-forward with publication-aware training cutoffs
  pipeline.py    end to end, writes web/forecast.json
web/             mobile-first front end, no dependencies
tests/           timing and leakage guards
```

## Status and limits

- **Synthetic data is the default fallback.** If the live sources are
  unreachable, `--source auto` generates a synthetic series and marks the
  output `data_source: synthetic`, which the web app surfaces as a warning
  banner. Backtest numbers on synthetic data verify the machinery; they say
  nothing about real-world accuracy.
- **The GLA scraper is untested against the live page.** It parses HTML and
  raises rather than guessing if the markup has changed — verify it on first
  run.
- **The 80% interval runs slightly narrow** on synthetic data (~77%
  coverage). Worth recalibrating on real data before trusting the band.
- **National average only.** Per-station forecasting is the intended next
  step and needs [CBS 81567NED](https://www.cbs.nl/nl-nl/cijfers/detail/81567NED)
  plus station-level discount structure, motorway-vs-local effects and local
  competition.
