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
if [[ "${RUNNER_OS:-}" == "Windows" && $windows_cross_compile -eq 1 ]]; then
  # Cross builds use the cross test binaries, not the native sharded helpers.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-test-bin$' || true)"
else
  # Native builds, including Windows MSVC, lint the native test binaries.
  # Query runs before platform analysis, so remove the cross-only helpers.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-windows-cross-bin$' || true)"
fi

if [[ "${RUNNER_OS:-}" == "Windows" ]]; then
  # Expanding a manual label turns Bazel's platform skip into an analysis
  # error. This process test only supports UnixProcessDriver (Linux/macOS).
  manual_rust_test_targets="$(
    printf '%s\n' "${manual_rust_test_targets}" |
      grep -Fxv -- "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin" || true
  )"
fi

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
