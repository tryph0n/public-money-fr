#!/usr/bin/env bash
# Open an issue for a failed data refresh, or comment on the one that is still open.
# Input (environment): FAILED_STEP, LOG_DIR, RUN_URL, GH_TOKEN, GH_REPO; HF_TOKEN
# is optional and only used to keep its value out of the issue.
set -euo pipefail

title="Data refresh failed"
log="$LOG_DIR/$FAILED_STEP.log"
error_line="no error line in the log"
if [ -f "$log" ]; then
  error_line="$(grep -m1 -E '^(ERROR|Error)' "$log" || tail -n 1 "$log")"
fi
# The issue is public: remove the token value, and anything that looks like a Hugging Face token.
if [ -n "${HF_TOKEN:-}" ]; then
  error_line="${error_line//"$HF_TOKEN"/***}"
fi
error_line="$(printf '%s' "$error_line" | sed -E 's/hf_[A-Za-z0-9]{10,}/***/g')"

case "$FAILED_STEP" in
  fetch)
    host="$(printf '%s' "$error_line" | grep -m1 -oE 'https?://[^/ ]+' | sed -E 's#https?://##' || true)"
    host="${host:-unknown, see the error line}"
    advice="Check that the host answers, then run the workflow again."
    ;;
  pins)
    host="the pinned file is named in the error line"
    advice="A pinned file changed upstream and nothing was published. Read the date of last update again at the page named in the error line, update the manifest and the lockfile in a pull request; the next run publishes."
    ;;
  publish)
    host="huggingface.co"
    advice="The error is the error of the Hugging Face library. Check the token and the datasets, then run the workflow again."
    ;;
  forced)
    host="test.invalid"
    advice="This failure was forced by a manual run to test this issue path."
    ;;
  *)
    host="none, a local step failed"
    advice="Read the log of the step."
    ;;
esac

# Step, host and error line come from a log: show them in a code fence longer than any run of
# backticks in them, so that GitHub renders no markdown and no mention.
details="$(printf 'Step: %s\nHost: %s\nError: %s' "$FAILED_STEP" "$host" "$error_line")"
longest="$(printf '%s' "$details" | tr -c '`' '\n' | awk '{ if (length($0) > m) m = length($0) } END { print m + 0 }')"
fence="$(printf '`%.0s' $(seq 1 $((longest > 2 ? longest + 1 : 3))))"
body="$(printf '%s\n%s\n%s\n\nRun: %s\n\n%s\n' "$fence" "$details" "$fence" "$RUN_URL" "$advice")"

open="$(gh issue list --state open --search "\"$title\" in:title" --json number,title \
  --jq "[.[] | select(.title == \"$title\")] | first | .number // empty")"

if [ -n "$open" ]; then
  gh issue comment "$open" --body "$body"
  echo "Commented on issue #$open"
else
  gh issue create --title "$title" --body "$body"
fi
