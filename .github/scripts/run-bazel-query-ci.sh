#!/usr/bin/env bash

set -euo pipefail

# Run target-discovery queries with the same startup settings as the main
# build/test invocation so they can reuse the same Bazel server. Ordinary
# queries remain pre-analysis. --configured explicitly requests cquery so the
# caller can supply the same platform options as its build; it executes no
# build or test actions and does not itself select remote execution.

query_command=query
if [[ "${1:-}" == "--configured" ]]; then
  query_command=cquery
  shift
fi

if [[ $# -lt 2 || "${@: -2:1}" != "--" ]]; then
  echo "Usage: $0 [--configured] [<bazel query args>...] -- <query expression>" >&2
  exit 1
fi

query_args=("${@:1:$#-2}")
query_expression="${@: -1}"

run_bazel() {
  if [[ "${RUNNER_OS:-}" == "Windows" ]]; then
    MSYS2_ARG_CONV_EXCL='*' "$(dirname "${BASH_SOURCE[0]}")/run_bazel_with_buildbuddy.py" "$@"
    return
  fi

  "$(dirname "${BASH_SOURCE[0]}")/run_bazel_with_buildbuddy.py" "$@"
}

bazel_query_args=("${query_command}")

if [[ -n "${BAZEL_REPO_CONTENTS_CACHE:-}" ]]; then
  bazel_query_args+=("--repo_contents_cache=${BAZEL_REPO_CONTENTS_CACHE}")
fi

if [[ -n "${BAZEL_REPOSITORY_CACHE:-}" ]]; then
  bazel_query_args+=("--repository_cache=${BAZEL_REPOSITORY_CACHE}")
fi

if (( ${#query_args[@]} > 0 )); then
  bazel_query_args+=("${query_args[@]}")
fi
bazel_query_args+=("$query_expression")

run_bazel "${bazel_query_args[@]}"
