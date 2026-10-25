#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

windows_cross_compile=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --windows-cross-compile)
      windows_cross_compile=1
      shift
      ;;
    *)
      echo "Usage: $0 [--windows-cross-compile]" >&2
      exit 1
      ;;
  esac
done

# Resolve the dynamic targets before printing anything so callers do not
# continue with a partial list if `bazel query` fails. Target discovery is
# local on all platforms.
manual_rust_test_targets="$(
  ./.github/scripts/run-bazel-query-ci.sh \
    --output=label \
    -- 'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))'
)"
if [[ "${RUNNER_OS:-}" != "Windows" || $windows_cross_compile -eq 0 ]]; then
  # Native clippy jobs, including Windows MSVC, lint native test binaries.
  # Windows-cross helpers require WINDOWS_GNULLVM_ONLY and must not be
  # explicitly requested for a native platform. Their native counterparts
  # remain selected through the package pattern and manual native helpers.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-windows-cross-bin$' || true)"
elif [[ $windows_cross_compile -eq 1 ]]; then
  # `bazel query` is intentionally pre-analysis and does not remove targets
  # made incompatible by `target_compatible_with`. Sharded integration tests
  # add native-only manual helpers such as `core-all-test-bin`, plus separate
  # `core-all-test-windows-cross-bin` helpers for the Windows cross leg. Keep
  # the Windows helpers and unit-test helpers, but do not pass the native-only
  # sharded integration helpers as explicit clippy targets.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-test-bin$' || true)"
fi

if [[ "${RUNNER_OS:-}" == "Windows" && $windows_cross_compile -eq 0 ]]; then
  # This one native helper is Linux/macOS-only in _COGNITIVE_E2E_COMPATIBILITY.
  # Keep it on those hosts, and keep every other native/manual MSVC helper.
  # The package pattern remains: platform analysis, not a test skip, excludes
  # its incompatible public wrapper on Windows.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | awk '$0 != "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"')"
fi

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
