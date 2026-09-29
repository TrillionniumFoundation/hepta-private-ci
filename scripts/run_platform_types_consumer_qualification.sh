#!/usr/bin/env bash
# Every independent check runs; the aggregate remains failed if any check fails.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
MANIFEST="$ROOT/codex-rs/Cargo.toml"
INITIAL_HEAD="$(git rev-parse HEAD)" || exit 1
INITIAL_TREE="$(git rev-parse HEAD^{tree})" || exit 1
INITIAL_STATUS="$(git status --porcelain --untracked-files=normal)" || exit 1
EVIDENCE="${HEPTA_TYPES_EVIDENCE_DIR:-$ROOT/.hepta-evidence/platform-types-consumers}"
mkdir -p "$EVIDENCE" || exit 1
rm -f "$EVIDENCE/execution.json" || exit 1
RESULTS="$EVIDENCE/results.tsv"
: > "$RESULTS"
failed=0
run_step() {
  local name="$1"; shift
  local rc=0 start=$SECONDS
  printf '\n=== %s ===\n' "$name"
  "$@" > "$EVIDENCE/$name.log" 2>&1 || rc=$?
  cat "$EVIDENCE/$name.log"
  case "$name" in
    manifest-rust|types-tests|wire-tests|ndu-tests|prompt-producer|prompt-ledger|topology-consumer|manifest-owners)
      if (( rc == 0 )); then
        python3 scripts/platform_types_nonempty_tests.py "$EVIDENCE/$name.log" \
          > "$EVIDENCE/$name-count.json" || rc=$?
      fi
      ;;
  esac
  printf '%s\t%s\t%s\n' "$name" "$rc" "$((SECONDS-start))" >> "$RESULTS"
  if (( rc != 0 )); then failed=1; fi
}
run_rust() {
  (cd "$ROOT/codex-rs" && "$@")
}
run_step consumer-map python3 scripts/verify_platform_types_consumers.py
run_step canonical-python python3 codex-rs/hepta-types/conformance/verify_vectors.py
run_step canonical-node bash -c 'node --input-type=module < codex-rs/hepta-types/conformance/verify_vectors.ts'
run_step rejections-python python3 codex-rs/hepta-types/conformance/verify_rejections.py
run_step rejections-node node codex-rs/hepta-types/conformance/verify_rejections.mjs
run_step manifest-python python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
run_step manifest-node node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
run_step wire-python python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
run_step wire-node node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
run_step generated-drift python3 codex-rs/hepta-types/bindings/generate_bindings.py --check
run_step binding-python python3 codex-rs/hepta-types/bindings/verify_generated.py
run_step binding-node node codex-rs/hepta-types/bindings/verify_generated.mjs
run_step consumer-compile run_rust cargo check --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-types -p codex-hepta-wire -p codex-hepta-ndu \
  -p codex-hepta-codex-adapter -p codex-hepta-learning-ledger \
  -p codex-hepta-supervisor --lib
run_step manifest-rust run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-types --test manifest_protocol_consumer
run_step types-tests run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-types --all-targets
run_step wire-tests run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-wire --lib
run_step ndu-tests run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-ndu --lib
run_step prompt-producer run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-codex-adapter --lib prompt_delivery
run_step prompt-ledger run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-learning-ledger --lib runtime_delivery
run_step topology-consumer run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-supervisor --lib topology_candidate
run_step manifest-owners run_rust cargo test --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-supervisor --lib platform_manifest_admission
run_step types-lint run_rust cargo clippy --locked --manifest-path "$MANIFEST" -p codex-hepta-types --all-targets -- -D warnings
run_step wire-lint run_rust cargo clippy --locked --manifest-path "$MANIFEST" -p codex-hepta-wire --lib -- -D warnings
run_step ndu-lint run_rust cargo clippy --locked --manifest-path "$MANIFEST" -p codex-hepta-ndu --lib -- -D warnings
python3 - "$ROOT" "$EVIDENCE" "$INITIAL_HEAD" "$INITIAL_TREE" "$INITIAL_STATUS" <<'RECEIPT'
import hashlib, json, pathlib, subprocess, sys
root, evidence = map(pathlib.Path, sys.argv[1:3])
initial_head, initial_tree, initial_status = sys.argv[3:6]
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
checks = []
for row in (evidence / "results.tsv").read_text().splitlines():
    name, rc, seconds = row.split("\t")
    log = evidence / (name + ".log")
    checks.append({"name": name, "exitCode": int(rc), "seconds": int(seconds),
                   "log": log.name, "logSha256": hashlib.sha256(log.read_bytes()).hexdigest()})
final_head, final_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
unchanged = (initial_head, initial_tree) == (final_head, final_tree)
clean = not initial_status and not git("status", "--porcelain", "--untracked-files=normal")
passed = len(checks) == 24 and all(row["exitCode"] == 0 for row in checks)
record = {"schema": "hepta.platform-types.consumer-execution.v2", "sourceHead": initial_head,
          "sourceTree": initial_tree, "finalSourceHead": final_head, "finalSourceTree": final_tree,
          "sourceUnchanged": unchanged, "cleanWorktree": clean,
          "checksPassed": passed, "qualified": passed and clean and unchanged, "checks": checks,
          "productActivation": False, "independentAcceptance": False}
(evidence / "execution.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({key: record[key] for key in ("sourceHead", "checksPassed", "qualified")}))
if not unchanged or not clean or not passed:
    raise SystemExit("consumer qualification requires all 24 checks and a clean unchanged candidate")
RECEIPT
receipt_rc=$?
if (( receipt_rc != 0 )); then failed=1; fi
exit "$failed"
