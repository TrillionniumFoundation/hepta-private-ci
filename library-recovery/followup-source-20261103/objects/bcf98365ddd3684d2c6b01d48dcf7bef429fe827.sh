#!/usr/bin/env bash
# Hepta exact-head source qualification for Draft PR #57 (stacked on PR #54). Deliberately no remote deployment.
# Usage: bash hepta_full_local_gate_20261023.sh /path/to/hepta-private-ci /path/to/hepta-runtime
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s /absolute/path/to/hepta-private-ci /absolute/path/to/hepta-runtime\n' "$0" >&2
  exit 64
fi
HEPTA=$1
RUNTIME=$2
HEPTA_SHA='f8c9419df6ddeb36ff8b522a50219981fb8d9345'
HEPTA_TREE='15c9d6ea07bf3832de82825a6cc1e8c958dd3d45'
RUNTIME_SHA='22f6f6db5264607eeab825e8b623c51dc97c0caf'
RUNTIME_TREE='91a042c9f5bf3737fc5d5d56efd7978331205cf6'

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'BLOCKED: required executable missing: %s\n' "$1" >&2
    exit 69
  fi
}
verify_tree() {
  local label=$1 repo=$2 sha=$3 tree=$4
  if [[ "$repo" != /* || ! -d "$repo" ]] || ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'BLOCKED: %s is not an absolute, accessible Git worktree: %s\n' "$label" "$repo" >&2
    exit 66
  fi
  local observed_head observed_tree
  observed_head=$(git -C "$repo" rev-parse HEAD)
  observed_tree=$(git -C "$repo" rev-parse 'HEAD^{tree}')
  if [[ "$observed_head" != "$sha" || "$observed_tree" != "$tree" ]]; then
    printf 'BLOCKED: %s exact-source mismatch\nexpected_sha=%s\nactual_sha=%s\nexpected_tree=%s\nactual_tree=%s\n' \
      "$label" "$sha" "$observed_head" "$tree" "$observed_tree" >&2
    exit 70
  fi
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    printf 'BLOCKED: %s worktree has uncommitted changes; refuse to qualify a dirty candidate\n' "$label" >&2
    exit 71
  fi
}

# No provenance report or PASS markers are emitted before basic admissibility.
require_tool git
verify_tree 'hepta-private-ci' "$HEPTA" "$HEPTA_SHA" "$HEPTA_TREE"
verify_tree 'hepta-runtime' "$RUNTIME" "$RUNTIME_SHA" "$RUNTIME_TREE"
for tool in rustc cargo rustfmt cargo-clippy just python3 sha256sum; do require_tool "$tool"; done
if ! rustc --version | grep -Eq '^rustc 1\.95\.0 '; then
  printf 'BLOCKED: expected Rust 1.95.0, observed %s\n' "$(rustc --version)" >&2
  exit 72
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence_root=${HEPTA_EVIDENCE_ROOT:-"$HOME/hepta-qualification"}
dest="$evidence_root/${stamp}-${RUNTIME_SHA:0:12}"
mkdir -p "$dest"
manifest="$dest/manifest.txt"
cat >"$manifest" <<EOF
scope=source-only,not-production
status=IN_PROGRESS
utc=$stamp
host=$(hostname)
hepta_sha=$HEPTA_SHA
hepta_tree=$HEPTA_TREE
runtime_sha=$RUNTIME_SHA
runtime_tree=$RUNTIME_TREE
rustc=$(rustc --version)
cargo=$(cargo --version)
EOF
finalize() {
  local rc=$1
  if [[ $rc -ne 0 ]]; then
    sed -i 's/^status=IN_PROGRESS$/status=BLOCKED/' "$manifest"
    printf 'script_exit=%d\n' "$rc" >>"$manifest"
  fi
  ( cd "$dest" && sha256sum ./*.log manifest.txt > SHA256SUMS ) 2>/dev/null || true
  printf 'Evidence directory: %s\n' "$dest"
}
trap 'finalize $?' EXIT
run_gate() {
  local label=$1 repo=$2
  shift 2
  printf 'RUN %s\n' "$label"
  if ( cd "$repo" && "$@" ) >"$dest/$label.log" 2>&1; then
    printf '%s=PASS\n' "$label" >>"$manifest"
  else
    local rc=$?
    printf '%s=FAIL:%d\n' "$label" "$rc" >>"$manifest"
    printf 'BLOCKED: %s exited %d; inspect %s/%s.log\n' "$label" "$rc" "$dest" "$label" >&2
    return "$rc"
  fi
}
# Fail fast on genuine source failures; never report an aggregate PASS if any gate failed.
run_gate runtime-fmt "$RUNTIME" cargo fmt --all -- --check
run_gate runtime-check "$RUNTIME" cargo check --locked --all-targets
run_gate runtime-clippy "$RUNTIME" cargo clippy --locked --all-targets -- -D warnings
run_gate runtime-test "$RUNTIME" cargo test --locked --all-targets
run_gate runtime-release "$RUNTIME" cargo build --locked --release
run_gate hepta-fmt "$HEPTA" just fmt-check
run_gate hepta-check "$HEPTA" cargo check --manifest-path codex-rs/Cargo.toml --locked --workspace --all-targets
run_gate hepta-clippy "$HEPTA" cargo clippy --manifest-path codex-rs/Cargo.toml --locked --workspace --all-targets -- -D warnings
run_gate hepta-test "$HEPTA" just test
run_gate hepta-release "$HEPTA" cargo build --manifest-path codex-rs/Cargo.toml --locked --workspace --release
sed -i 's/^status=IN_PROGRESS$/status=SOURCE_GATES_PASS_ONLY/' "$manifest"
printf '\nSOURCE GATES PASS for pinned SHA and tree only.\n'
printf 'NOT TESTED: physical devices, SSH effect ACK loss, independent final-use grants, Cell training, benchmark, acceptance, promotion, release.\n'
