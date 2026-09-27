#!/usr/bin/env bash
set -euo pipefail

kind="${1:?qualification kind is required}"
expected_sha="${2:?expected commit SHA is required}"
evidence_dir="${3:?evidence directory is required}"
profile="${4:?qualification profile is required}"

case "$kind" in
  source-head|merge-candidate) ;;
  *) echo "unsupported qualification kind: $kind" >&2; exit 2 ;;
esac
case "$profile" in
  exact-head|merge-candidate) ;;
  *) echo "unsupported qualification profile: $profile" >&2; exit 2 ;;
esac

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
test "$(git rev-parse HEAD)" = "$expected_sha"
mkdir -p "$evidence_dir"
failed=0

run_logged() {
  local label="$1"
  shift
  printf '%q ' "$@" > "$evidence_dir/$label.command.txt"
  printf '\n' >> "$evidence_dir/$label.command.txt"
  set +e
  "$@" 2>&1 | tee "$evidence_dir/$label.log"
  local code="${PIPESTATUS[0]}"
  set -e
  printf '%s\n' "$code" > "$evidence_dir/$label.exit-code"
  if [[ "$code" -ne 0 ]]; then
    failed=1
  fi
}

run_benchmark() {
  local command=(
    cargo run
    --manifest-path codex-rs/Cargo.toml
    --locked
    -p codex-hepta-cognitive-read
    --example cognitive_read_bench
    --quiet
  )
  printf '%q ' "${command[@]}" > "$evidence_dir/benchmark.command.txt"
  printf '\n' >> "$evidence_dir/benchmark.command.txt"
  set +e
  "${command[@]}" \
    > "$evidence_dir/benchmark.json" \
    2> "$evidence_dir/benchmark.stderr.log"
  local code="$?"
  set -e
  cat "$evidence_dir/benchmark.stderr.log"
  printf '%s\n' "$code" > "$evidence_dir/benchmark.exit-code"
  if [[ "$code" -ne 0 ]]; then
    failed=1
  fi
}

run_logged workspace-manifest \
  python3 .github/scripts/verify_cargo_workspace_manifests.py
run_logged contract-limits \
  python3 scripts/verify-cognitive-read-constants.py
run_logged implementation-map \
  python3 scripts/verify-cognitive-read-map.py --expected-sha "$expected_sha"
run_logged core-tests \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-cognitive-read --lib
run_logged fuzz-harness \
  cargo check \
    --manifest-path codex-rs/hepta-cognitive-read/fuzz/Cargo.toml \
    --all-targets
rm -f codex-rs/hepta-cognitive-read/fuzz/Cargo.lock

if [[ "$profile" == "exact-head" ]]; then
  run_benchmark
  run_logged product-read-replay \
    cargo test --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-agentd \
      --test cognitive_product_e2e \
      real_agentd_local_memory_review_is_read_only_and_replayable -- \
      --exact --test-threads=1
  run_logged product-write-smoke \
    cargo test --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-agentd \
      --features qualification-cognitive-write \
      --test cognitive_product_e2e \
      real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends -- \
      --exact --test-threads=1
fi

run_logged qualification-receipt \
  python3 scripts/emit-cognitive-read-qualification.py \
    --kind "$kind" \
    --expected-sha "$expected_sha" \
    --evidence-dir "$evidence_dir" \
    --output "$evidence_dir/qualification-receipt.json"

(
  cd "$evidence_dir"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum
) > "$evidence_dir/SHA256SUMS"

bundle="$RUNNER_TEMP/cognitive-read-$kind-$expected_sha.tar"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 \
  --numeric-owner -cf "$bundle" \
  -C "$repo_root" "${evidence_dir#"$repo_root"/}"
sha256sum "$bundle" > "$bundle.sha256"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "failed=$failed"
    echo "bundle=$bundle"
    echo "bundle_sha=$bundle.sha256"
  } >> "$GITHUB_OUTPUT"
fi
