#!/usr/bin/env bash
# Compatibility navigation entry point. The canonical, evidence-bound runner is
# owned next to the real matrixd test and immediately re-execs a verified Bash.
set -euo pipefail

script=${BASH_SOURCE[0]}
case "$script" in
  /*) ;;
  *) script=$PWD/$script ;;
esac
script_dir=${script%/*}
repo_root=$(cd "$script_dir/../.." && pwd -P)
canonical="$repo_root/codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh"
[[ -f "$canonical" && -x "$canonical" ]] || {
  echo "canonical channel.matrix Synapse runner is unavailable: $canonical" >&2
  exit 69
}
exec "$canonical" "$@"
