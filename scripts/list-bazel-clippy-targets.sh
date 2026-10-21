#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

windows_cross_compile=0
windows_msvc=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --windows-cross-compile)
      windows_cross_compile=1
      shift
      ;;
    --windows-msvc)
      windows_msvc=1
      shift
      ;;
    *)
      echo "Usage: $0 [--windows-cross-compile | --windows-msvc]" >&2
      exit 1
      ;;
  esac
done

if [[ $windows_cross_compile -eq 1 && $windows_msvc -eq 1 ]]; then
  echo "--windows-cross-compile and --windows-msvc are mutually exclusive" >&2
  exit 1
fi

# Resolve the dynamic targets before printing anything so callers do not
# continue with a partial list if `bazel query` fails. Target discovery is
# local on all platforms.
manual_rust_test_targets="$(
  ./.github/scripts/run-bazel-query-ci.sh \
    --output=label \
    -- 'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))'
)"
# Native Windows Bazel writes CRLF; normalize before suffix matching.
manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | sed $'s/\r$//')"
if [[ "${RUNNER_OS:-}" != "Windows" || $windows_msvc -eq 1 ]]; then
  # Non-Windows and Windows MSVC clippy jobs lint native test binaries.
  # Windows-cross helpers require the gnullvm ABI, not merely Windows.
  # Keep native sharded and unit-test helpers in this roster.
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

if [[ "${RUNNER_OS:-}" == "Windows" ]]; then
  # This manual process harness uses UnixProcessDriver and Unix sockets and
  # is explicitly incompatible with Windows in hepta-agentd/BUILD.bazel.
  # Keep its separate, Windows-compatible writer qualification helper.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -F -x -v -- '//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin' || true)"
fi

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
