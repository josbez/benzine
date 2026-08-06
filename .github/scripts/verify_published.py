"""Check that the site actually serves the forecast we just built.

Pushing to `gh-pages` reports success the moment the branch moves, which is
not the same thing as the site being updated -- and on this repository the
two have never yet coincided: every Pages deployment so far has stalled on
`deployment_in_progress` and timed out (see the README). A run that pushes
and stops looks green while the site serves nothing at all.

So the run does not finish until the published `forecast.json` carries the
`generated_at` of the build that just ran.

Usage: verify_published.py <local forecast.json> [timeout-seconds]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

POLL_SECONDS = 10
DEFAULT_TIMEOUT = 300


def site_url() -> str:
    """The Pages URL for this repository, derived from the runner's env."""
    owner, _, repo = os.environ["GITHUB_REPOSITORY"].partition("/")
    # A repository named `<owner>.github.io` is served from the domain root;
    # every other one gets a subpath.
    root = f"https://{owner}.github.io"
    return root if repo.lower() == f"{owner.lower()}.github.io" else f"{root}/{repo}"


def published_generated_at(url: str) -> str | None:
    """`generated_at` as currently served, or None if it is not there yet."""
    # Pages sits behind a CDN that will happily serve the previous copy for
    # minutes; a changing query string is what makes this a live check.
    bust = f"{url}?cachebust={time.time()}"
    request = urllib.request.Request(bust, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response).get("generated_at")
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        print(f"  not readable yet: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    local = json.loads(open(sys.argv[1]).read())["generated_at"]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TIMEOUT
    url = f"{site_url()}/forecast.json"

    print(f"waiting for {url} to serve generated_at={local}")
    deadline = time.monotonic() + timeout
    live = None
    while time.monotonic() < deadline:
        live = published_generated_at(url)
        if live == local:
            print("the site is serving this run's forecast")
            return 0
        if live:
            print(f"  site still serving generated_at={live}")
        time.sleep(POLL_SECONDS)

    print(
        f"::error title=Site not updated::{url} still serves "
        f"generated_at={live!r} after {timeout}s, expected {local!r}. "
        "The build and the push succeeded, so this is the Pages deployment "
        "itself -- check for a stalled deployment in the github-pages "
        "environment and the Pages source setting."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
