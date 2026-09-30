#!/usr/bin/env bash
set -euo pipefail

platform="${1:?platform is required}"
expected_runner="${2:-}"
root="$(git rev-parse --show-toplevel)"
evidence_dir="${KG_PLATFORM_EVIDENCE_DIR:-$root/artifacts/knowledge-graph-platform}"
mkdir -p "$evidence_dir"
cd "$root"

if [[ -n "$expected_runner" ]]; then
  test "${RUNNER_NAME:-}" = "$expected_runner"
fi

test "$(git rev-parse HEAD)" = "${GITHUB_SHA:-$(git rev-parse HEAD)}"
git diff --exit-code
git diff --cached --exit-code

case "$platform" in
  linux)
    test "${RUNNER_OS:-Linux}" = "Linux"
    sudo apt-get update
    sudo apt-get install -y \
      build-essential bubblewrap libcap-dev pkg-config protobuf-compiler
    command -v protoc
    protoc --version
    sudo sysctl -w kernel.unprivileged_userns_clone=1
    if sysctl kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
      sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    fi
    ;;
  macos)
    test "${RUNNER_OS:-macOS}" = "macOS"
    if ! command -v protoc >/dev/null 2>&1; then
      brew install protobuf
    fi
    command -v protoc
    protoc --version
    ;;
  *)
    printf 'unsupported platform: %s\n' "$platform" >&2
    exit 2
    ;;
esac

checks_tsv="$evidence_dir/checks.tsv"
: > "$checks_tsv"
failures=0

run_check() {
  local check_id="$1"
  shift
  local log="$evidence_dir/${check_id}.log"
  local started_ns finished_ns duration_ms exit_code status digest
  started_ns="$(python3 -c 'import time; print(time.time_ns())')"
  set +e
  "$@" >"$log" 2>&1
  exit_code=$?
  set -e
  cat "$log"
  finished_ns="$(python3 -c 'import time; print(time.time_ns())')"
  duration_ms=$(( (finished_ns - started_ns) / 1000000 ))
  digest="$(python3 - "$log" <<'PY'
import hashlib
import sys
from pathlib import Path
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
  if [[ "$exit_code" -eq 0 ]]; then
    status="passed"
  else
    status="failed"
    failures=$((failures + 1))
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$check_id" "$status" "$exit_code" "$duration_ms" "$digest" "$(basename "$log")" \
    >> "$checks_tsv"
}

run_check status \
  python3 scripts/hepta_kg_status.py --check
run_check documentation_sync \
  python3 scripts/hepta_kg_documentation_sync.py --check
run_check implementation_map \
  python3 scripts/hepta_knowledge_graph_map_verify.py \
    --expected-sha "$(git rev-parse HEAD)" \
    --expected-tree "$(git rev-parse HEAD^{tree})"
run_check evidence_tooling \
  bash -lc 'python3 -m unittest discover -s scripts -p "test_hepta_kg_*.py" -v'
run_check workspace_formatting \
  bash -lc 'cd codex-rs && cargo fmt --all -- --check'
run_check verified_v8 \
  env CODEX_REPO_ROOT="$root" PYTHONPATH=scripts \
    python3 scripts/hepta_ci_v8.py
run_check kg_kernel \
  bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-kg --all-features -- --nocapture'
run_check prompt_optimizer \
  bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-prompt-optimizer -- --nocapture'
run_check sqlite_owner \
  bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-memory --lib cognitive_kg_oracle_tests:: -- --nocapture --test-threads=1'
if [[ "$platform" == "linux" ]]; then
  run_check agentd_product \
    bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-agentd --test cognitive_product_e2e -- --nocapture --test-threads=1'
else
  run_check agentd_product_compile \
    bash -lc 'cd codex-rs && cargo check --locked -p codex-hepta-agentd --all-targets'
fi
run_check strict_clippy \
  bash -lc 'cd codex-rs && cargo clippy --locked -p codex-hepta-kg -p codex-hepta-prompt-optimizer -p codex-hepta-memory -p codex-hepta-agentd --no-deps --all-targets --all-features -- -D warnings'
run_check tracked_source_clean \
  bash -lc 'git diff --exit-code && git diff --cached --exit-code && test -z "$(git status --porcelain --untracked-files=no)"'

SOURCE_SHA="$(git rev-parse HEAD)" \
SOURCE_TREE="$(git rev-parse HEAD^{tree})" \
PLATFORM="$platform" \
CHECKS_TSV="$checks_tsv" \
RECEIPT="$evidence_dir/platform-receipt.json" \
python3 - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess
from pathlib import Path


def output(*command: str) -> str:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:  # evidence generation must survive missing optional tools
        return f"unavailable: {exc}"

checks = []
for line in Path(os.environ["CHECKS_TSV"]).read_text().splitlines():
    check_id, status, exit_code, duration_ms, digest, log = line.split("\t")
    checks.append(
        {
            "id": check_id,
            "status": status,
            "exitCode": int(exit_code),
            "durationMs": int(duration_ms),
            "logSha256": digest,
            "log": log,
        }
    )
all_passed = bool(checks) and all(item["status"] == "passed" for item in checks)
receipt = {
    "schema": "hepta.kg.platform-qualification.v1",
    "sourceSha": os.environ["SOURCE_SHA"],
    "sourceTree": os.environ["SOURCE_TREE"],
    "platform": os.environ["PLATFORM"],
    "runnerName": os.environ.get("RUNNER_NAME"),
    "runnerOs": os.environ.get("RUNNER_OS"),
    "runnerArch": os.environ.get("RUNNER_ARCH"),
    "host": platform.platform(),
    "rustc": output("rustc", "--version"),
    "cargo": output("cargo", "--version"),
    "protoc": output("protoc", "--version"),
    "recordedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    "checks": checks,
    "allChecksPassed": all_passed,
    "candidateEvidenceOnly": True,
    "operatorAcceptance": False,
    "activation": False,
    "release": False,
}
Path(os.environ["RECEIPT"]).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
PY

if [[ "$failures" -ne 0 ]]; then
  printf '%s knowledge.graph qualification check(s) failed; receipt preserved at %s\n' \
    "$failures" "$evidence_dir/platform-receipt.json" >&2
  exit 1
fi

printf 'All knowledge.graph source checks passed. This is execution evidence only; it does not grant operator acceptance, activation, or release.\n'
