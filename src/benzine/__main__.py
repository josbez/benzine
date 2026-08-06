"""Command line entry point: python -m benzine <command>."""
from __future__ import annotations

import argparse

from . import backtest as bt
from . import pipeline
from .config import HORIZONS


def main() -> None:
    parser = argparse.ArgumentParser(prog="benzine")
    parser.add_argument(
        "command", choices=["build", "backtest", "forecast", "all"],
        help="build the panel, evaluate models, publish a forecast, or all three",
    )
    parser.add_argument(
        "--source", default="auto", choices=["auto", "live", "synthetic"],
        help="where to get data; 'auto' falls back to synthetic when offline",
    )
    parser.add_argument("--model", default="gbm", choices=["naive", "ecm", "gbm"])
    parser.add_argument("--refit-every", type=int, default=30)
    args = parser.parse_args()

    print(f"[1] building panel (source={args.source})")
    panel, pump, resolved = pipeline.build(args.source)
    print(f"    {len(panel):,} rows, {panel['date'].min().date()} -> "
          f"{panel['date'].max().date()}, source={resolved}")

    if args.command == "build":
        return

    metrics = None
    if args.command in ("backtest", "all"):
        print("[2] walk-forward backtest")
        result = bt.run(panel, refit_every=args.refit_every)
        metrics = result.metrics
        print()
        print(result.summary())
        print()
        if resolved == "synthetic":
            print("    NOTE: synthetic data -- these numbers verify the pipeline,")
            print("          they do not estimate real-world accuracy.")
        result.predictions.to_parquet(
            pipeline.PROCESSED / "backtest_predictions.parquet", index=False
        )

    if args.command in ("forecast", "all"):
        print("[3] publishing forecast")
        payload = pipeline.publish_forecast(
            panel, pump, metrics, model_name=args.model, data_source=resolved,
            horizons=HORIZONS,
        )
        anchor = payload["anchor"]
        print(f"    anchor {anchor['price']:.3f} ({anchor['source']}, "
              f"{anchor['date']}, {anchor['staleness_days']}d old)")
        for row in payload["forecast"]:
            print(f"    +{row['horizon']}d {row['date']}  "
                  f"{row['q50']:.3f}  [{row['q10']:.3f} - {row['q90']:.3f}]")
        print("    -> web/forecast.json")


if __name__ == "__main__":
    main()
