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

## Deploying it

The whole thing is a static page plus one generated JSON file, so it needs
no server. Two GitHub Actions workflows cover it, free:

| Workflow | When | What |
|---|---|---|
| `daily.yml` | 05:00 UTC daily | scrape the advisory price, rebuild the forecast, publish to GitHub Pages |
| `backtest.yml` | Mondays | re-run the walk-forward evaluation, commit the scores |

They are split because the daily run takes well under a minute while the
backtest takes several — and its scores barely move day to day. The daily
job reads the cached scores from `data/backtest_metrics.json`.

The site is published by pushing `web/` to a **`gh-pages`** branch, not
through the Pages deployment API. Set **Settings → Pages → Source: Deploy
from a branch → `gh-pages` / `(root)`** once, after the first run has
created the branch.

The branch is force-pushed as a single commit each time. It holds
generated output only, so its history is worth nothing and letting it grow
would cost clone time forever.

### Pages has never actually served anything — what is known, 6 Aug 2026

Facts, in the order they were established:

- The deployment-API route (`configure-pages` / `upload-pages-artifact` /
  `deploy-pages`) repeatedly created a deployment and then sat on
  `deployment_in_progress` until it timed out.
- Switching to a branch push did **not** sidestep that. Pushing to
  `gh-pages` triggers GitHub's own *pages build and deployment* workflow,
  which runs `deploy-pages` internally and stalls in the same place (run
  `31110887125`). So the branch route buys less than the earlier version
  of this README claimed.
- **Settings → Pages** is configured correctly: *Deploy from a branch*,
  `gh-pages` / `(root)`. This was verified, not assumed. A source mismatch
  is therefore not the explanation.
- GitHub had a live Actions incident that evening whose status updates
  named Pages explicitly ("GitHub Pages may experience failures or
  delays"), with jobs queued and never picked up. Whether it also covers
  the earlier stalls depends on when the incident began, which was not
  established.

What that adds up to: the cause is **not identified**. It is somewhere in
Pages' own deployment machinery, and nothing in this repository has been
shown to influence it. Resist the temptation to write a convincing story
here — the previous version of this section argued at length that a branch
push could not be blocked by a deployment stall, and the logs then showed
exactly that happening.

The order to work through, cheapest first:

1. Re-run the daily workflow once GitHub reports the incident resolved.
   That is the one test that has not been run under normal conditions.
2. Cancel anything stuck in the `github-pages` environment
   (`gh api repos/josbez/benzine/deployments` → `POST .../statuses` with
   `state=inactive`), then re-run.
3. Check `github-pages` for environment protection rules waiting on an
   approval nobody is giving.
4. If it still will not deploy, publish `web/` to Netlify or Cloudflare
   Pages instead — three static files and one JSON, so the hosting choice
   carries no weight.

The daily run ends with a healthcheck that polls the live `forecast.json`
until it carries the `generated_at` of the build that just ran, and fails
otherwise. Until Pages serves, the workflow therefore goes red every day —
deliberately, because the alternative is a green run publishing to a site
nobody is serving. The advisory price is committed long before that step,
so a red run costs no data.

The branch push is kept regardless: it is less machinery than the artifact
route (no artifact, no environment, no deployment to poll), which is a
reason to prefer it but was never a reason to expect it to fix a stall.

Two things worth knowing:

- **The daily run is what builds the advisory-price history.** There is no
  public archive, so `data/raw/gla_history.csv` is committed back to the
  repo on each run and grows one row per day. Miss a day and that day is
  gone for good — which is the main reason to deploy this sooner rather
  than later. The scrape and its commit are therefore the *first* steps of
  the job, ahead of everything that is allowed to fail; a failed scrape
  opens an issue rather than logging a warning nobody reads.
- **CI runs `--source live`, never `auto`.** If a feed is down the build
  goes red instead of quietly publishing a synthetic forecast as if it were
  real. The offline fallback is for development only.

GitHub delays scheduled workflows under load, and disables them entirely
after 60 days without repository activity. The daily commit counts as
activity, so this is self-sustaining as long as the advisory-price scrape
keeps working — but if the site goes stale, check that first.

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

Evaluation covers the **most recent five years**, while training still
expands over everything before each refit. That bound is not primarily
about runtime: the panel reaches back to 2006, and how the model would have
done in 2008 says little about how it does now — different excise regime,
different retail structure, and a large share of the sample sitting inside
the 2008 and 2020 price collapses. A headline accuracy averaged over
eighteen years mostly measures history. Pass `--test-years 0` to score the
whole panel anyway.

Output is a set of quantiles (10/25/50/75/90), not a single line, so the app
can show a widening band instead of implying false precision.

## Data sources

| Source | What | Role |
|---|---|---|
| [CBS 80416ned](https://www.cbs.nl/nl-nl/cijfers/detail/80416ned) | daily national average pump price | training label |
| [UnitedConsumers GLA](https://www.unitedconsumers.com/tanken/info/gemiddelde-landelijke-adviesprijs) | daily advisory price | live anchor |
| Yahoo Finance, then Stooq (RBOB, Brent, EUR/USD) | wholesale market | leading indicator |
| `data/excise.yaml` | accijns schedule | known future steps |

RBOB stands in for the real EBOB Rotterdam assessment, which is a paid
Argus/Platts product. Swapping in a licensed EBOB feed means changing
`sources/market.py` and nothing else.

Each market series is tried against Yahoo Finance first and Stooq second,
and each provider is retried three times with exponential backoff before
the next one is tried. That redundancy is not paranoia: Stooq serves a
block page rather than CSV to datacentre IP ranges, so it works from a
laptop and fails from a GitHub runner — and a single provider is a single
point of failure for the whole daily job.

The full history is downloaded once and cached; later runs ask Yahoo for a
six-month window and splice it over the cache, with freshly fetched rows
winning on overlapping dates so revisions are picked up. Asking for twenty
years of ticks every morning is both wasteful and a good way to earn a
rate limit. The caches expire after twelve hours, so a local run cannot
quietly keep using whatever it first downloaded.

One known weakness in the proxy: `RB=F` is the **continuous front-month**
RBOB contract, so it carries a discontinuity at every roll. RBOB rolls are
not small — the summer/winter blend switch puts a visible step into the
series each spring and autumn. The model reads those steps as genuine
wholesale moves. A real EBOB assessment has no such artefact, and until one
is wired in, expect the roll months to be the model's worst.

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
- **The GLA scraper is untested against the live page.** It parses the
  page's text (tags stripped) and raises with an excerpt rather than
  guessing, so a failure in CI shows what the page actually contained.
- **The advisory price only becomes the anchor after ~10 overlapping days.**
  It is a list price from the five majors while CBS is volume-weighted
  across all stations including discounters, so the two sit cents apart.
  Until that offset is estimated the anchor stays on CBS — otherwise the
  displayed price would jump on the first day the scraper works.
- **The 80% interval runs slightly narrow** on synthetic data (~77%
  coverage). Worth recalibrating on real data before trusting the band.
- **National average only.** Per-station forecasting is the intended next
  step and needs [CBS 81567NED](https://www.cbs.nl/nl-nl/cijfers/detail/81567NED)
  plus station-level discount structure, motorway-vs-local effects and local
  competition.
