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

# Reuse the build wrapper's target, host/exec, cache, and credential policy.
# Configured discovery is required: loading-only query also returns helpers
# whose target_compatible_with rejects the platform used by the Clippy build.
query_wrapper_args=(--configured-query)
query_bazel_args=(--config=clippy)
case "${RUNNER_OS:-}" in
  Windows)
    if [[ $windows_cross_compile -eq 1 ]]; then
      query_wrapper_args+=(--windows-cross-compile)
    else
      query_wrapper_args+=(--windows-msvc-host-platform)
      query_bazel_args+=(--platforms=//:windows_x86_64_msvc)
    fi
    ;;
  Linux | macOS)
    if [[ $windows_cross_compile -eq 1 ]]; then
      echo "Windows cross discovery requires RUNNER_OS=Windows." >&2
      exit 1
    fi
    ;;
  "")
    if [[ $windows_cross_compile -eq 1 ]]; then
      echo "Windows cross discovery requires RUNNER_OS=Windows." >&2
      exit 1
    fi
    # The public local recipe invokes plain bazel build --config=clippy.
    query_wrapper_args+=(--local-default-config)
    ;;
  *)
    echo "Unknown Bazel Clippy runner role: ${RUNNER_OS}" >&2
    exit 1
    ;;
esac

# cquery analyzes every wildcard target before applying kind(). Loading query
# first keeps unrelated multi-platform release bundles out of that universe.
# The configured pass still checks every discovered manual Rust test.
loading_labels="$(mktemp)"
trap 'rm -f "$loading_labels"' EXIT
./.github/scripts/run-bazel-query-ci.sh --output=label \
  -- 'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))' \
  > "$loading_labels"
configured_expression="$(
  python3 ./.github/scripts/bazel_clippy_target_records.py \
    --loading-expression "$loading_labels"
)"
manual_rust_test_records="$(
  ./.github/scripts/run-bazel-ci.sh \
    "${query_wrapper_args[@]}" -- cquery \
    "${query_bazel_args[@]}" \
    --output=starlark \
    --starlark:expr='("incompatible" if "IncompatiblePlatformProvider" in providers(target) else "compatible") + "\t" + str(target.label)' \
    -- "$configured_expression"
)"
manual_rust_test_targets="$(
  printf '%s\n' "${manual_rust_test_records}" \
    | python3 ./.github/scripts/bazel_clippy_target_records.py \
      --expected-labels "$loading_labels"
)"

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
