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

# Resolve the complete manual target list before printing any build patterns.
# Query failures must not turn into a partial successful lint selection.
manual_rust_test_query='kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))'
manual_rust_test_targets="$(
  ./.github/scripts/run-bazel-query-ci.sh \
    --output=label -- "${manual_rust_test_query}"
)"
if [[ "${RUNNER_OS:-}" == "Windows" && $windows_cross_compile -eq 0 ]]; then
  # Native MSVC must honor declared compatibility, including GNU-cross helpers
  # and Unix-only owner fixtures. Keep every compatible manual Rust test;
  # suffix filtering cannot express the latter platform constraints.
  # Discover all candidates before analysis: cquery on //... would also analyze
  # unrelated manual release transitions before applying kind/attr filters.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | sed $'s/\r$//; /^$/d')"
  if [[ -z "${manual_rust_test_targets}" ]]; then
    echo "Unconfigured Clippy query returned no manual Rust test helpers" >&2
    exit 1
  fi
  # A relative query file works with native Windows and MSYS conversion disabled,
  # and keeps the complete candidate set out of the Windows command-line limit.
  query_file="$(mktemp .bazel-clippy-query.XXXXXXXX)"
  trap 'rm -f -- "${query_file}"' EXIT
  {
    printf 'config(set(\n'
    while IFS= read -r label; do
      # Bazel query words do not interpret backslash escapes. Use a quote that
      # is absent from this label so operators and spaces remain literal.
      if [[ "${label}" != *\"* ]]; then
        printf '"%s"\n' "${label}"
      elif [[ "${label}" != *\'* ]]; then
        printf "'%s'\n" "${label}"
      else
        echo "Manual Rust test helper contains both query quote characters" >&2
        exit 1
      fi
    done <<< "${manual_rust_test_targets}"
    # A reused server can retain exec or older configurations of the same label.
    printf '), target)\n'
  } > "${query_file}"
  manual_rust_test_targets="$(
    ./.github/scripts/run-bazel-query-ci.sh \
      --configured \
      --config=ci-windows \
      --config=clippy \
      --platforms=//:windows_x86_64_msvc \
      --host_platform=//:local_windows_msvc \
      --output=starlark \
      '--starlark:expr="//%s:%s" % (target.label.package, target.label.name) if "IncompatiblePlatformProvider" not in providers(target) else ""' \
      --query-file "${query_file}"
  )"
  rm -f -- "${query_file}"
  trap - EXIT
  # cquery emits an empty line for each incompatible configured target.
  # Native Windows stdout uses CRLF; remove each record's one trailing CR.
  manual_rust_test_targets="$(printf '%s\n' "${manual_rust_test_targets}" | sed $'s/\r$//; /^$/d')"
  if [[ -z "${manual_rust_test_targets}" ]]; then
    echo "Configured Clippy query returned no manual Rust test helpers" >&2
    exit 1
  fi
elif [[ "${RUNNER_OS:-}" != "Windows" ]]; then
  # Non-Windows clippy jobs lint the native test binaries; the
  # Windows-cross binaries exist only for the fast Windows test leg.
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

printf '%s\n' \
  "//codex-rs/..." \
  "-//codex-rs/v8-poc:all"

# `--config=clippy` on the `workspace_root_test` wrappers does not lint the
# underlying `rust_test` binaries. Add the internal manual `*-unit-tests-bin`
# targets explicitly so inline `#[cfg(test)]` code is linted like
# `cargo clippy --tests`.
printf '%s\n' "${manual_rust_test_targets}"
