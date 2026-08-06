"""Excise duty schedule -- the one input we genuinely know in advance.

Announced accijns changes are deterministic jumps in the pump price. Feeding
the schedule in as a known future step is free forecasting skill that no
purely statistical model would ever find on its own.
"""
from __future__ import annotations

import pandas as pd
import yaml

from ..config import DATA

_SCHEDULE = DATA / "excise.yaml"


def schedule(fuel: str = "euro95") -> pd.DataFrame:
    spec = yaml.safe_load(_SCHEDULE.read_text())
    rows = spec[fuel]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def vat_rate() -> float:
    return float(yaml.safe_load(_SCHEDULE.read_text())["vat_rate"])


def series(dates: pd.DatetimeIndex, fuel: str = "euro95") -> pd.Series:
    """Excise rate in force on each of `dates`, extended into the future."""
    sched = schedule(fuel).set_index("date")["rate"]
    idx = pd.DatetimeIndex(dates)
    full = sched.reindex(sched.index.union(idx)).ffill()
    return full.reindex(idx).bfill().rename("excise")
