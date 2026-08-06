#!/usr/bin/env bash
#
# Commit one file and get it onto main, even if something else pushed first.
#
# Two workflows write to main -- the daily forecast and the weekly backtest
# -- and Dependabot pushes too. On a Monday morning all three overlap, and a
# bare `git push` simply loses that race with "fetch first". For the backtest
# scores that costs a re-run; for the advisory price it costs the day, because
# there is no public archive to fetch it from later.
#
# Usage: commit-and-push.sh <path> <commit message>
set -euo pipefail

path="$1"
message="$2"
attempts="${PUSH_ATTEMPTS:-3}"
backoff="${PUSH_BACKOFF:-4}"
branch="${GITHUB_REF_NAME:-main}"

if [ ! -e "$path" ]; then
  echo "nothing to commit: $path does not exist"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Stage first, then compare against the index: on the very first run the
# file is untracked, and `git diff` alone does not see untracked files --
# so day one would never be recorded.
git add "$path"
if git diff --cached --quiet; then
  echo "no change to commit in $path"
  exit 0
fi

git commit -m "$message"

for attempt in $(seq 1 "$attempts"); do
  if git push origin "HEAD:$branch"; then
    echo "pushed on attempt $attempt"
    exit 0
  fi

  if [ "$attempt" -eq "$attempts" ]; then
    break
  fi

  echo "push rejected; rebasing onto origin/$branch and retrying in ${backoff}s"
  sleep "$backoff"
  backoff=$((backoff * 2))
  # `|| true`, because the whole point of retrying is that the network is
  # unreliable: under `set -e` a failed fetch would abort the script here,
  # skipping both the remaining attempts and the diagnostic below.
  #
  # --rebase, not merge: these commits are single-file bookkeeping, and a
  # merge commit per race would bury the history in noise. Rebasing cannot
  # conflict here in practice -- each workflow owns a different file.
  git pull --rebase origin "$branch" || git rebase --abort || true
done

echo "::error title=Push failed::Could not push $path to $branch after \
$attempts attempts. If this is the advisory price, today's value is lost."
exit 1
