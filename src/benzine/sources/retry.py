"""Retrying a flaky network call, the same way for every source.

This lives in one place because the first version of it did not. The
market feeds got retries after a run failed on a timeout; CBS did not, and
two days later the weekly backtest died on

    [Errno 101] Network is unreachable  (opendata.cbs.nl)

on a runner that had reached the same host successfully two hours
earlier. The same fault, the same fix, one source late.
"""
from __future__ import annotations

import random
import time

ATTEMPTS = 3
BACKOFF = 2.0  # seconds before the second attempt, doubled after that
JITTER = 0.5   # fraction of the delay drawn at random, to avoid lockstep


def sleep_before_retry(attempt: int) -> None:
    """Exponential backoff with jitter.

    The jitter matters more than it looks: several series are fetched in
    the same second from the same provider, so without it they retry in
    lockstep and hit a rate limit together every time.
    """
    delay = BACKOFF * 2 ** (attempt - 1)
    time.sleep(delay * (1 + random.uniform(-JITTER, JITTER)))


def with_retries(call, describe: str = "request"):
    """Run ``call`` until it stops raising, up to ``ATTEMPTS`` times.

    Every failure is printed rather than swallowed: a run that succeeded
    on the third attempt still says something about the source, and that
    is worth seeing in a log before it becomes a run that fails on all
    three.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - retry any transport fault
            if attempt == ATTEMPTS:
                raise
            print(
                f"  {describe} failed on attempt {attempt}/{ATTEMPTS} "
                f"({type(exc).__name__}: {exc}); retrying"
            )
            sleep_before_retry(attempt)
