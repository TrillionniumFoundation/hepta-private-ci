#!/usr/bin/env bash
# Produce repair material only after the workflow's strict lock check failed.
set -euo pipefail

diagnostic="${1:?diagnostic output directory required}"
mkdir -p "$diagnostic"
cp MODULE.bazel.lock "$diagnostic/MODULE.bazel.lock.before"
sha256sum MODULE.bazel.lock > "$diagnostic/original-lock-sha256.txt"
restore_lock() {
  local original_status=$?
  cp "$diagnostic/MODULE.bazel.lock.before" MODULE.bazel.lock
  sha256sum --check "$diagnostic/original-lock-sha256.txt" || exit 1
  exit "$original_status"
}
trap restore_lock EXIT
git rev-parse HEAD > "$diagnostic/checkout-commit.txt"
git rev-parse 'HEAD^{tree}' > "$diagnostic/checkout-tree.txt"
sha256sum MODULE.bazel codex-rs/Cargo.lock codex-rs/Cargo.toml .bazelversion \
  > "$diagnostic/input-sha256.txt"
generation_status=0
just bazel-lock-update || generation_status=$?
printf '%s\n' "$generation_status" > "$diagnostic/generation-exit-code.txt"
cp MODULE.bazel.lock "$diagnostic/MODULE.bazel.lock.generated"
git diff --binary -- MODULE.bazel.lock > "$diagnostic/MODULE.bazel.lock.diff"
sha256sum "$diagnostic/MODULE.bazel.lock.before" \
  "$diagnostic/MODULE.bazel.lock.generated" > "$diagnostic/lock-sha256.txt"
sha256sum --check "$diagnostic/input-sha256.txt"
# The earlier strict step remains failed. These files do not qualify the lock.
exit "$generation_status"
