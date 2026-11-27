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

runner_os="${RUNNER_OS:-}"
if [[ -z "${runner_os}" ]]; then
  case "$(uname -s)" in
    Linux) runner_os=Linux ;;
    Darwin) runner_os=macOS ;;
    MINGW*|MSYS*|CYGWIN*) runner_os=Windows ;;
    *) echo "Unsupported host platform for Bazel clippy target selection" >&2; exit 1 ;;
  esac
fi
case "${runner_os}" in
  Linux|macOS|Windows) ;;
  *) echo "Unsupported RUNNER_OS: ${runner_os}" >&2; exit 1 ;;
esac
if [[ $windows_cross_compile -eq 1 && "${runner_os}" != "Windows" ]]; then
  echo "--windows-cross-compile requires a Windows runner" >&2
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
# Native Windows query output may use CRLF. Strip only the record's trailing
# CR before anchored suffix and exact-label matching.
manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | sed $'s/\r$//')"
if [[ $windows_cross_compile -eq 0 ]]; then
  # All native clippy jobs, including Windows MSVC, lint native test binaries;
  # Windows-cross binaries exist only for the fast Windows test leg.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-windows-cross-bin$' || true)"
  if [[ "${runner_os}" == "Windows" ]]; then
    # This one manual harness uses UnixProcessDriver and Unix sockets. Its
    # _COGNITIVE_E2E_COMPATIBILITY in codex-rs/hepta-agentd/BUILD.bazel permits
    # only Linux/macOS. Keep it in those native lint jobs; retain every other
    # native manual test here, including sharded *-test-bin helpers.
    manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -Fvx -- '//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin' || true)"
  fi
elif [[ $windows_cross_compile -eq 1 ]]; then
  # `bazel query` is intentionally pre-analysis and does not remove targets
  # made incompatible by `target_compatible_with`. Sharded integration tests
  # add native-only manual helpers such as `core-all-test-bin`, plus separate
  # `core-all-test-windows-cross-bin` helpers for the Windows cross leg. Keep
  # the Windows helpers and unit-test helpers, but do not pass the native-only
  # sharded integration helpers as explicit clippy targets.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | grep -v -- '-test-bin$' || true)"
fi

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
