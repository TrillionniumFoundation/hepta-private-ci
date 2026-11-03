#!/usr/bin/env bash
# Source-only qualification matrix. Does not merge/deploy/promote or authorize effects.
# Usage: bash hepta_full_blocker_matrix_20261023.sh HEPTA_MAIN HEPTA_SECURITY_PR2717 RUNTIME_PR47 RUNTIME_PR61
set -Eeuo pipefail

if (( $# != 4 )); then
  echo "Usage: $0 /abs/hepta-main /abs/hepta-pr2717 /abs/runtime-pr47 /abs/runtime-pr61" >&2
  exit 64
fi

HEPTA_MAIN=$1
HEPTA_SECURITY=$2
RUNTIME_INTEGRATION=$3
RUNTIME_HARDENING=$4

declare -A EXPECTED_SHA=(
  [hepta_main]=f8c9419df6ddeb36ff8b522a50219981fb8d9345
  [hepta_security]=812bfc41b9d25b6ee764c66be094088cc11668dd
  [runtime_integration]=a8a1deef5499da952ba0747f4ed54f4f6b1766a6
  [runtime_hardening]=4d32ba361452b0040c530ab6c0596672716d48d0
)
declare -A EXPECTED_TREE=(
  [hepta_main]=15c9d6ea07bf3832de82825a6cc1e8c958dd3d45
  [hepta_security]=a9e390def38ff881e8654251ef13f7a2f4a7a71e
  [runtime_integration]=a62b48efe1d2d0db2d0196a68e3b99a59f3a0700
  [runtime_hardening]=30a002d03e65accb7cdbb9c3e3bcca164480817a
)
declare -A REPO=(
  [hepta_main]="$HEPTA_MAIN"
  [hepta_security]="$HEPTA_SECURITY"
  [runtime_integration]="$RUNTIME_INTEGRATION"
  [runtime_hardening]="$RUNTIME_HARDENING"
)
LANES=(hepta_main hepta_security runtime_integration runtime_hardening)

die() {
  local code=$1; shift
  printf 'BLOCKED: %s\n' "$*" >&2
  exit "$code"
}
require() {
  command -v "$1" >/dev/null 2>&1 || die 69 "missing tool $1"
}
require git
# Validate ALL lanes and immutable object identities before even creating a PASS-looking artifact.
for lane in "${LANES[@]}"; do
  path=${REPO[$lane]}
  [[ $path == /* && -d $path ]] || die 66 "$lane is not an accessible absolute worktree: $path"
  git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die 66 "$lane is not a Git worktree"
  head_sha=$(git -C "$path" rev-parse HEAD)
  tree_sha=$(git -C "$path" rev-parse 'HEAD^{tree}')
  [[ "$head_sha" == "${EXPECTED_SHA[$lane]}" ]] ||
    die 70 "$lane head mismatch: expected ${EXPECTED_SHA[$lane]}; actual $head_sha"
  [[ "$tree_sha" == "${EXPECTED_TREE[$lane]}" ]] ||
    die 70 "$lane tree mismatch: expected ${EXPECTED_TREE[$lane]}; actual $tree_sha"
  [[ -z "$(git -C "$path" status --porcelain)" ]] ||
    die 71 "$lane worktree dirty; source qualification refused"
done
for command_name in rustc cargo rustfmt rustup just python3 sha256sum timeout; do
  require "$command_name"
done
rustc --version | grep -Eq '^rustc 1\.95\.0 ' ||
  die 72 "Rust 1.95.0 required; observed $(rustc --version)"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
root=${HEPTA_GATE_OUTPUT:-"$HOME/hepta-qualification"}
dest="$root/matrix-$stamp"
mkdir -p "$dest"
summary="$dest/manifest.txt"
{
  echo "run_id=$stamp"
  echo "status=IN_PROGRESS"
  echo "qualification=source_only"
  echo "not_qualified=physical_SSH,SFTP,independent_FinalUse,Codex_bridge,Agent_Loop,Cell_learning,scale_performance,integrated_merge,operator_signoff"
  echo "rustc=$(rustc --version)"
  echo "cargo=$(cargo --version)"
  for lane in "${LANES[@]}"; do
    echo "$lane.sha=${EXPECTED_SHA[$lane]}"
    echo "$lane.tree=${EXPECTED_TREE[$lane]}"
  done
} >"$summary"

finalize() {
  rc=$1
  if [[ "$rc" -ne 0 ]]; then
    sed -i 's/^status=IN_PROGRESS$/status=SOURCE_BLOCKED/' "$summary"
    printf 'exit=%d\n' "$rc" >>"$summary"
  fi
  (
    cd "$dest"
    sha256sum -- *.log manifest.txt >SHA256SUMS 2>/dev/null || true
  )
  printf 'Qualification output: %s\n' "$dest" >&2
}
trap 'finalize $?' EXIT

# HEPTA_GATE_TIMEOUT_SECONDS applies per command, never bypasses a failed test.
time_limit=${HEPTA_GATE_TIMEOUT_SECONDS:-5400}
[[ "$time_limit" =~ ^[0-9]+$ && "$time_limit" -ge 60 && "$time_limit" -le 21600 ]] ||
  die 64 "HEPTA_GATE_TIMEOUT_SECONDS must be an integer between 60 and 21600"

gate() {
  local lane=$1 label=$2
  shift 2
  local path=${REPO[$lane]}
  printf 'RUN: %s [%s]\n' "$label" "$lane"
  if (cd "$path" && timeout --foreground "${time_limit}s" "$@") \
      >"$dest/${lane}_${label}.log" 2>&1; then
    printf '%s.%s=PASS\n' "$lane" "$label" >>"$summary"
  else
    result=$?
    printf '%s.%s=FAIL:%d\n' "$lane" "$label" "$result" >>"$summary"
    die "$result" "$lane/$label failed with $result; see $dest/${lane}_${label}.log"
  fi
}
for lane in runtime_integration runtime_hardening; do
  gate "$lane" fmt cargo fmt --all -- --check
  gate "$lane" check cargo check --locked --all-targets
  gate "$lane" clippy cargo clippy --locked --all-targets -- -D warnings
  gate "$lane" test cargo test --locked --all-targets
  gate "$lane" release cargo build --locked --release
done
for lane in hepta_main hepta_security; do
  gate "$lane" fmt just fmt-check
  gate "$lane" check cargo check --manifest-path codex-rs/Cargo.toml --locked --workspace --all-targets
  gate "$lane" clippy cargo clippy --manifest-path codex-rs/Cargo.toml --locked --workspace --all-targets -- -D warnings
  gate "$lane" test just test
  gate "$lane" release cargo build --manifest-path codex-rs/Cargo.toml --locked --workspace --release
done

sed -i 's/^status=IN_PROGRESS$/status=SEPARATE_SOURCE_LANES_PASS_ONLY/' "$summary"
echo 'Source-only lanes passed. Integration/cross-branch conflict resolution and physical acceptance remain blocked.'
