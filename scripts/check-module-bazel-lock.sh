#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Fetch, integrity, configuration and interruption failures are not evidence of
# lockfile drift. Keep Bazel's own diagnostics and exact status; do not retry or
# rewrite MODULE.bazel.lock when its validation could not complete.
exec "${repo_root}/.github/scripts/run_bazel_with_buildbuddy.py" mod deps --lockfile_mode=error
