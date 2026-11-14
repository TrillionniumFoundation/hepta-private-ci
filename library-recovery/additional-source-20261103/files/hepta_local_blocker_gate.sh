#!/usr/bin/env bash
# Hepta MemoryCell read-only source/CI gate runner.
# Does not merge, reset, modify tracked files, accept, promote or deploy.
# Usage: HEPTA_EXPECT_SHA=<40-character Git SHA> bash hepta_local_blocker_gate.sh /absolute/path/to/hepta-private-ci
set -Eeuo pipefail

repo="${1:-}"
expected="${HEPTA_EXPECT_SHA:-}"
if [[ -z "$repo" || "$repo" != /* ]]; then
  printf 'BLOCKED: supply absolute repository path as first argument\n' >&2; exit 2
fi
if ! [[ "$expected" =~ ^[a-f0-9]{40}$ ]]; then
  printf 'BLOCKED: HEPTA_EXPECT_SHA must be the approved exact 40-hex HEAD\n' >&2; exit 2
fi
if ! command -v git >/dev/null || ! command -v python3 >/dev/null; then
  printf 'BLOCKED: requires git and python3\n' >&2; exit 2
fi
if ! git -C "$repo" rev-parse --show-toplevel >/dev/null 2>&1; then
  printf 'BLOCKED: not a Git worktree: %s\n' "$repo" >&2; exit 2
fi
root="$(git -C "$repo" rev-parse --show-toplevel)"
if [[ "$root" != "$repo" ]]; then
  printf 'BLOCKED: path must be exact repository root, got %s\n' "$root" >&2; exit 2
fi
origin="$(git -C "$repo" remote get-url origin 2>/dev/null || :)"
if ! [[ "$origin" =~ ^(https://github\.com/|git@github\.com:)TrillionniumFoundation/hepta-private-ci(\.git)?$ ]]; then
  printf 'BLOCKED: origin not verified for hepta-private-ci: %s\n' "$origin" >&2; exit 2
fi
head="$(git -C "$repo" rev-parse HEAD)"
if [[ "$head" != "$expected" ]]; then
  printf 'BLOCKED: HEAD drift; expected %s, got %s\n' "$expected" "$head" >&2; exit 2
fi
if [[ -n "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'BLOCKED: dirty worktree; preserve uncommitted edits, create isolated clean worktree\n' >&2; exit 2
fi
if [[ ! -f "$repo/docs/DEVELOPMENT.md" || ! -f "$repo/codex-rs/Cargo.toml" ]]; then
  printf 'BLOCKED: canonical DEVELOPMENT.md/Cargo.toml missing\n' >&2; exit 2
fi
for cmd in cargo rustc just; do
  if ! command -v "$cmd" >/dev/null; then
    printf 'BLOCKED: missing required Rust toolchain command %s\n' "$cmd" >&2; exit 2
  fi
done

out="${HEPTA_GATE_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/hepta-blockers.XXXXXXXX")}" 
if [[ "$out" == "$root" || "$out" == "$root"/* ]]; then
  printf 'BLOCKED: output directory may not be inside repo\n' >&2; exit 2
fi
mkdir -p "$out"
out="$(cd "$out" && pwd -P)"
log="$out/summary.tsv"
printf 'name\tstatus\texit_code\tlog\n' > "$log"
printf 'repo=%s\nhead=%s\norigin=%s\nbranch=%s\ntree=%s\n' "$root" "$head" "$origin" "$(git -C "$repo" symbolic-ref --quiet --short HEAD || echo detached)" "$(git -C "$repo" rev-parse HEAD^{tree})" > "$out/source-receipt.txt"

failure=0
run_check() {
  local name="$1"; shift
  local path="$out/$name.log" rc=0
  printf 'RUN %s\n' "$name"
  (cd "$root" && "$@") > "$path" 2>&1 || rc=$?
  if ((rc!=0)); then
    failure=1
    printf '%s\tFAIL\t%d\t%s\n' "$name" "$rc" "$path" >> "$log"
    tail -n 15 "$path" >&2
  else
    printf '%s\tPASS\t0\t%s\n' "$name" "$path" >> "$log"
  fi
}

# A failure is recorded but not hidden by a later success.
run_check docs python3 scripts/hepta-docs.py verify --profile development
if [[ -d "$root/scripts/memory_cell_meta" ]]; then
  run_check reference_python python3 -m unittest discover -s scripts/memory_cell_meta -p 'test_*.py' -v
else
  printf 'reference_python\tNOT_PRESENT\t-\t-\n' >> "$log"
fi
run_check cargo_metadata bash -c 'cd codex-rs && cargo metadata --locked --format-version 1 > /dev/null'
run_check rustfmt bash -c 'cd codex-rs && cargo fmt --all -- --check'
for crate in codex-hepta-neuron codex-hepta-memory-retrieval codex-hepta-intelligence-eval codex-hepta-agentd; do
  run_check "test_${crate}" bash -c 'cd codex-rs && just test --locked -p "$1"' _ "$crate"
done
run_check rust_clippy bash -c 'cd codex-rs && cargo clippy --locked --workspace --all-targets -- -D warnings'
if command -v cargo-deny >/dev/null; then
  run_check cargo_deny bash -c 'cd codex-rs && cargo-deny check'
elif cargo --list 2>/dev/null | grep -Eq '^[[:space:]]+deny([[:space:]]|$)'; then
  run_check cargo_deny bash -c 'cd codex-rs && cargo deny check'
else
  printf 'cargo_deny\tNOT_RUN_TOOL_MISSING\t-\t-\n' >> "$log"
  failure=1
fi

# The complete Windows/macOS, GitHub Architecture, V8, security and independent
# future-time/efficacy/permission gates are NOT locally certified by this script.
for external in windows_native macos_arm64 architecture_required blocking_ci v8_canary independent_future_windows certified_deletion_unlearning cross_host_final_use; do
  printf '%s\tEXTERNAL_NOT_VERIFIED\t-\t-\n' "$external" >> "$log"
done
if [[ -n "$(git -C "$root" status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'worktree_clean_after\tFAIL\t1\t-\n' >> "$log"
  failure=1
else
  printf 'worktree_clean_after\tPASS\t0\t-\n' >> "$log"
fi
printf 'Source-local results: %s\n' "$log"
printf 'Global production acceptance: DENY_ALL / HOLD_NO_GO (external gates not verified)\n'
exit "$failure"
