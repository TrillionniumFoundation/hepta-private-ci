#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
status=0
"${repo_root}/.github/scripts/run_bazel_with_buildbuddy.py" mod deps --lockfile_mode=error || status=$?
if (( status != 0 )); then
  printf 'Bazel could not verify MODULE.bazel.lock (exit %s); see its diagnostics above.\n' "$status" >&2
  echo "Only if Bazel reports lockfile drift, run 'just bazel-lock-update' and commit the updated lockfile." >&2
fi
exit "$status"
