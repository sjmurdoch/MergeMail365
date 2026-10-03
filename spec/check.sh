#!/usr/bin/env bash
# Bounded model checking of spec/wizard.qnt with Apalache (via quint verify).
#
#   spec/check.sh buggy        # code before any fixes: each bug's invariant is violated
#   spec/check.sh partial      # code before the round 2 fixes (bugs 10-15)
#   spec/check.sh fixed        # current code: every invariant must hold
#   spec/check.sh --all fixed  # same, as one run of allInvariants: about as long
#                              # as a single invariant, but names no culprit
#
# Settings (env var or flag): QUINT / --quint (quint executable),
# MAX_STEPS / --max-steps (bound, default 16).
# Needs Java on PATH; Apalache listens on local port 8822.
set -euo pipefail

QUINT="${QUINT:-quint}"
MAX_STEPS="${MAX_STEPS:-16}"
target=""
together=""

while [ $# -gt 0 ]; do
    case "$1" in
        --quint) QUINT="$2"; shift 2 ;;
        --max-steps) MAX_STEPS="$2"; shift 2 ;;
        --all) together=1; shift ;;
        buggy|partial|fixed) target="$1"; shift ;;
        *) echo "usage: $0 [--quint PATH] [--max-steps N] [--all] buggy|partial|fixed" >&2; exit 2 ;;
    esac
done
if [ -z "$target" ]; then
    echo "usage: $0 [--quint PATH] [--max-steps N] [--all] buggy|partial|fixed" >&2
    exit 2
fi

cd "$(dirname "$0")"

invariants="noUntestedSend next4Honest next5Honest buttonsMatchFlags back6Usable sendScreenHonest sendScreenNotStuck stepNeedsData stopHonoured stoppedReported testNeedsSignIn sendNeedsSignIn noInteractiveAuthInJob canProgress noStepJump previewHonest runningSendVisible noConcurrentSends failedSendReported progressHonest newMergeClears"
if [ -n "$together" ]; then
    invariants="allInvariants"
fi
status=0

for inv in $invariants; do
    out=""
    if out="$("$QUINT" verify wizard.qnt --main="$target" --invariant="$inv" --max-steps="$MAX_STEPS" 2>&1)"; then
        result="holds"
    else
        if printf '%s\n' "$out" | grep -q 'found a counterexample'; then
            result="VIOLATED"
        else
            printf '%s\n' "$out" >&2
            result="ERROR"
            status=1
        fi
    fi
    printf '%-20s %s\n' "$inv" "$result"
    if [ "$result" = "VIOLATED" ]; then
        printf '%s\n' "$out" | grep -o 'lastAction: "[^"]*"' | sed 's/lastAction: //; s/"//g' | tr '\n' ' ' | sed 's/^/    trace: /'
        echo
        if [ "$target" = "fixed" ]; then
            status=1
        fi
    fi
done

exit "$status"
