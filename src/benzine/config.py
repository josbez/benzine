"""Central paths and constants."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
WEB = ROOT / "web"

for _d in (RAW, PROCESSED):
    _d.mkdir(parents=True, exist_ok=True)

# --- Dutch fuel price composition ---------------------------------------
VAT_RATE = 0.21  # levied over (product cost + excise)

# CBS OData, table 80416ned: pump prices per fuel type, per day.
CBS_TABLE = "80416ned"
CBS_BASE = "https://opendata.cbs.nl/ODataApi/odata"

# Fuel we forecast first. CBS codes these as "BenzineEuro95" style keys.
FUEL_EURO95 = "euro95"

# Backtest scores are expensive (minutes) and change slowly, so they are
# computed on their own schedule and cached here for the daily run to read.
# This file is committed -- it is a published accuracy claim, not a build
# artefact.
METRICS_FILE = DATA / "backtest_metrics.json"

# Forecast horizons, in days. Beyond 5 days the known wholesale move has
# fully passed through and we would be forecasting the oil market itself,
# which is not predictable -- so we deliberately stop at 5.
HORIZONS = (1, 2, 3, 4, 5)

# Quantiles for the fan chart.
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
