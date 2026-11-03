#!/usr/bin/env bash

set -euo pipefail

# Run target-discovery queries with the same startup settings as the main
# build/test invocation so they can reuse the same Bazel server. Queries only
# enumerate labels, so they intentionally do not select a CI build/test config
# or remote execution.

if [[ $# -lt 2 || "${@: -2:1}" != "--" ]]; then
  echo "Usage: $0 [<bazel query args>...] -- <query expression>" >&2
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

bazel_query_args=(query)

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

# Only explicit label output is a line-record protocol. Other output modes
# (including binary/proto output) must remain byte-for-byte unchanged.
query_output=""
read_query_output=0
# Bash 3.2 treats an empty array expansion as unbound under nounset.
if (( ${#query_args[@]} > 0 )); then
  for arg in "${query_args[@]}"; do
    if [[ $read_query_output -eq 1 ]]; then
      query_output="$arg"
      read_query_output=0
      continue
    fi
    case "$arg" in
      --output)
        read_query_output=1
        ;;
      --output=*)
        query_output="${arg#--output=}"
        ;;
    esac
  done
fi

if [[ "${RUNNER_OS:-}" == "Windows" && "$query_output" == "label" ]]; then
  # Native Windows Bazel emits CRLF. Publish labels only after the query
  # succeeds: process-substitution consumers cannot otherwise observe its
  # failure status and could mistake partial output for a complete roster.
  query_output_file="$(mktemp)"
  cleanup_query_output() {
    local query_status="$1"
    trap - EXIT
    if rm -f "$query_output_file"; then
      :
    else
      local cleanup_status=$?
      printf 'Failed to remove Bazel query label file: %s\n' "$query_output_file" >&2
      if [[ $query_status -eq 0 ]]; then
        query_status=$cleanup_status
      fi
    fi
    return "$query_status"
  }
  trap 'cleanup_query_output "$?"' EXIT

  query_status=0
  normalized_query_output=""
  if run_bazel "${bazel_query_args[@]}" > "$query_output_file"; then
    # A trailing sentinel keeps command substitution from removing newline
    # records. Nothing is published until normalization and cleanup succeed.
    if normalized_query_output="$(sed $'s/\r$//' "$query_output_file" && printf '.')"; then
      normalized_query_output="${normalized_query_output%.}"
    else
      query_status=$?
    fi
  else
    query_status=$?
  fi
  if cleanup_query_output "$query_status"; then
    printf '%s' "$normalized_query_output"
  else
    exit "$?"
  fi
else
  run_bazel "${bazel_query_args[@]}"
fi
