#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

qualification = r'''name: Hepta memory retrieval qualification

on:
  pull_request:
    paths:
      - "codex-rs/hepta-memory-retrieval/**"
      - "codex-rs/hepta-memory/**"
      - "codex-rs/hepta-agentd/**"
      - "codex-rs/hepta-learning-ledger/**"
      - "codex-rs/hepta-cognitive-types/**"
      - "codex-rs/hepta-types/**"
      - "codex-rs/Cargo.toml"
      - "codex-rs/Cargo.lock"
      - "rust-toolchain.toml"
      - "qualification/memory-retrieval/**"
      - "qualification/module-execution-dossiers/detail/memory.retrieval.md"
      - "docs/modules/memory.retrieval/**"
      - "scripts/verify_memory_retrieval_*.py"
      - "scripts/tests/test_verify_memory_retrieval_*.py"
      - ".github/actions/hepta-synthetic-merge/action.yml"
      - ".github/workflows/hepta-memory-retrieval-qualification-host.yml"
      - ".github/workflows/blocking-ci.yml"
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: read
  id-token: write
  attestations: write

concurrency:
  group: hepta-memory-retrieval-qualification-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

env:
  SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
  BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before || '' }}
  CARGO_INCREMENTAL: "0"
  CARGO_BUILD_JOBS: "2"

jobs:
  source-head:
    name: Memory retrieval exact source
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
      - name: Check out exact source
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - uses: ./.github/actions/setup-ci
      - uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582 # 1.95.0
      - name: Resolve verified V8 inputs
        env:
          CODEX_REPO_ROOT: ${{ github.workspace }}
          PYTHONPATH: scripts
        run: python3 scripts/hepta_ci_v8.py
      - name: Verify exact source identity and governance
        env:
          GH_TOKEN: ${{ github.token }}
          EVENT_NAME: ${{ github.event_name }}
          PR_NUMBER: ${{ github.event.pull_request.number || '' }}
          REPOSITORY: ${{ github.repository }}
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          records="$RUNNER_TEMP/memory-retrieval-source"
          mkdir -p "$records"
          git show "$BASE_SHA:docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json" > "$records/base-map.json" 2>/dev/null || printf '{}\n' > "$records/base-map.json"
          cp docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json "$records/head-map.json"
          if [ "$EVENT_NAME" = pull_request ]; then
            gh api --paginate --slurp "repos/$REPOSITORY/pulls/$PR_NUMBER/reviews" > "$records/reviews.json"
          else
            printf '[]\n' > "$records/reviews.json"
          fi
          python3 scripts/verify_memory_retrieval_review.py \
            --base-map "$records/base-map.json" --head-map "$records/head-map.json" \
            --event-json "$GITHUB_EVENT_PATH" --reviews-json "$records/reviews.json" \
            --head-sha "$SOURCE_SHA" --output "$records/review-gate.json"
      - name: Run exact-source qualification
        env:
          TESTED_SHA: ${{ env.SOURCE_SHA }}
          HEPTA_CI_LANE: source-head
        shell: bash
        run: |
          set -euo pipefail
          records="$RUNNER_TEMP/memory-retrieval-source"
          python3 -m unittest -v scripts.tests.test_verify_memory_retrieval_review scripts.tests.test_verify_memory_retrieval_benchmark
          python3 scripts/hepta_ci_exec.py --output "$records/fmt.json" -- bash -lc 'cd codex-rs && cargo fmt --all -- --check'
          python3 scripts/hepta_ci_exec.py --output "$records/tests.json" -- bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger'
          python3 scripts/hepta_ci_exec.py --output "$records/clippy.json" -- bash -lc 'cd codex-rs && cargo clippy --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger --all-targets -- -D warnings'
          python3 scripts/hepta_ci_exec.py --output "$records/docs.json" -- python3 scripts/hepta-docs.py verify
          python3 scripts/hepta_ci_exec.py --output "$records/maps.json" -- python3 scripts/hepta-implementation-maps.py verify
          python3 scripts/hepta_ci_exec.py --output "$records/derived.json" -- python3 scripts/hepta-module-docs.py refresh-derived --check
          python3 - <<'PY' > "$records/candidate.json"
          import json, subprocess
          def git(*args): return subprocess.check_output(["git", *args], text=True).strip()
          parts = git("rev-list", "--parents", "-n", "1", "HEAD").split()
          print(json.dumps({"schemaVersion": 1, "kind": "memory_retrieval_exact_source", "commit": parts[0], "tree": git("rev-parse", "HEAD^{tree}"), "parents": parts[1:]}, indent=2, sort_keys=True))
          PY
      - name: Retain exact-source receipts
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: memory-retrieval-source-${{ env.SOURCE_SHA }}
          path: ${{ runner.temp }}/memory-retrieval-source/**
          if-no-files-found: error
          retention-days: 90

  merge-candidate:
    name: Memory retrieval deterministic merge
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
      - name: Check out source
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      - name: Construct deterministic synthetic merge
        id: merge
        uses: ./.github/actions/hepta-synthetic-merge
        with:
          base-sha: ${{ github.event.pull_request.base.sha }}
          source-sha: ${{ github.event.pull_request.head.sha }}
          pr-number: ${{ github.event.pull_request.number }}
          author-name: Hepta memory retrieval CI
          author-email: hepta-memory-retrieval-ci@users.noreply.github.com
          message: Synthetic memory retrieval merge
      - uses: ./.github/actions/setup-ci
      - uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582 # 1.95.0
      - name: Resolve verified V8 inputs
        env:
          CODEX_REPO_ROOT: ${{ github.workspace }}
          PYTHONPATH: scripts
        run: python3 scripts/hepta_ci_v8.py
      - name: Run synthetic-merge qualification
        env:
          SOURCE_SHA: ${{ github.event.pull_request.head.sha }}
          TESTED_SHA: ${{ steps.merge.outputs.sha }}
          HEPTA_CI_LANE: base-merge
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$TESTED_SHA"
          test "$(git rev-parse HEAD^{tree})" = "${{ steps.merge.outputs.tree }}"
          records="$RUNNER_TEMP/memory-retrieval-merge"
          mkdir -p "$records"
          python3 scripts/hepta_ci_exec.py --output "$records/fmt.json" -- bash -lc 'cd codex-rs && cargo fmt --all -- --check'
          python3 scripts/hepta_ci_exec.py --output "$records/tests.json" -- bash -lc 'cd codex-rs && cargo test --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger'
          python3 scripts/hepta_ci_exec.py --output "$records/clippy.json" -- bash -lc 'cd codex-rs && cargo clippy --locked -p codex-hepta-memory-retrieval -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-learning-ledger --all-targets -- -D warnings'
          python3 scripts/hepta_ci_exec.py --output "$records/docs.json" -- python3 scripts/hepta-docs.py verify
          python3 scripts/hepta_ci_exec.py --output "$records/maps.json" -- python3 scripts/hepta-implementation-maps.py verify
          python3 scripts/hepta_ci_exec.py --output "$records/derived.json" -- python3 scripts/hepta-module-docs.py refresh-derived --check
          python3 - <<'PY' > "$records/candidate.json"
          import json, subprocess
          def git(*args): return subprocess.check_output(["git", *args], text=True).strip()
          parts = git("rev-list", "--parents", "-n", "1", "HEAD").split()
          print(json.dumps({"schemaVersion": 1, "kind": "memory_retrieval_synthetic_merge", "commit": parts[0], "tree": git("rev-parse", "HEAD^{tree}"), "parents": parts[1:]}, indent=2, sort_keys=True))
          PY
      - name: Retain merge receipts
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: memory-retrieval-merge-${{ steps.merge.outputs.sha }}
          path: ${{ runner.temp }}/memory-retrieval-merge/**
          if-no-files-found: error
          retention-days: 90

  qualification-host:
    name: Memory retrieval qualification-host SLO
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
      - name: Check out exact source
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Bind source and host identity
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          mkdir -p "$RUNNER_TEMP/memory-retrieval-target-host"
          { printf 'source_commit=%s\n' "$(git rev-parse HEAD)"; printf 'source_tree=%s\n' "$(git rev-parse HEAD^{tree})"; printf 'runner_name=%s\n' "$RUNNER_NAME"; printf 'runner_os=%s\n' "$RUNNER_OS"; printf 'runner_arch=%s\n' "$RUNNER_ARCH"; uname -a; lscpu; free -b; rustc -Vv; cargo -V; /usr/bin/time --version; } > "$RUNNER_TEMP/memory-retrieval-target-host/host.txt" 2>&1
      - name: SQLite owner retrieval and revalidation probe
        working-directory: codex-rs
        run: /usr/bin/time -v cargo test --release --locked -p codex-hepta-memory target_host_owner_retrieval_reports_latency_percentiles -- --ignored --nocapture --test-threads=1 > "$RUNNER_TEMP/memory-retrieval-target-host/sqlite-owner.log" 2>&1
      - name: HNMF 512-candidate probe
        working-directory: codex-rs
        run: /usr/bin/time -v cargo test --release --locked -p codex-hepta-memory-retrieval target_host_hnmf_reports_latency_percentiles_at_candidate_ceiling -- --ignored --nocapture --test-threads=1 > "$RUNNER_TEMP/memory-retrieval-target-host/hnmf-512.log" 2>&1
      - name: HNMF structural-ceiling probe
        working-directory: codex-rs
        run: /usr/bin/time -v cargo test --release --locked -p codex-hepta-memory-retrieval target_host_hnmf_validates_full_structural_ceiling -- --ignored --nocapture --test-threads=1 > "$RUNNER_TEMP/memory-retrieval-target-host/hnmf-structural.log" 2>&1
      - name: Agentd complete retrieval-path probe
        working-directory: codex-rs
        run: /usr/bin/time -v cargo test --release --locked -p codex-hepta-agentd target_host_memory_retrieval_end_to_end_slo -- --ignored --nocapture --test-threads=1 > "$RUNNER_TEMP/memory-retrieval-target-host/agentd-e2e.log" 2>&1
      - name: Enforce limits and emit immutable receipt candidate
        shell: bash
        run: |
          set -euo pipefail
          root="$RUNNER_TEMP/memory-retrieval-target-host"
          python3 scripts/verify_memory_retrieval_benchmark.py \
            --log "$root/sqlite-owner.log" --log "$root/hnmf-512.log" \
            --log "$root/hnmf-structural.log" --log "$root/agentd-e2e.log" \
            --limits qualification/memory-retrieval/SLO_LIMITS.json --host "$root/host.txt" \
            --source-commit "$SOURCE_SHA" --source-tree "$(git rev-parse HEAD^{tree})" \
            --output "$root/receipt.json"
          sha256sum "$root"/* > "$root/SHA256SUMS"
      - name: Summarize qualification-host evidence
        if: always()
        run: |
          printf 'Source: `%s`\n\nGitHub-hosted qualification evidence is not production target-host acceptance.\n\n' "$SOURCE_SHA" >> "$GITHUB_STEP_SUMMARY"
          grep -h 'hepta.memory-retrieval' "$RUNNER_TEMP"/memory-retrieval-target-host/*.log >> "$GITHUB_STEP_SUMMARY" || true
      - name: Retain raw qualification evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: memory-retrieval-qualification-${{ github.run_id }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/memory-retrieval-target-host/**
          if-no-files-found: error
          retention-days: 90
      - name: Attest mainline qualification receipt provenance
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8 # v4.2.2
        with:
          subject-path: ${{ runner.temp }}/memory-retrieval-target-host/receipt.json
'''

(ROOT / ".github/workflows/hepta-memory-retrieval-qualification-host.yml").write_text(qualification, encoding="utf-8")

blocking_path = ROOT / ".github/workflows/blocking-ci.yml"
blocking = blocking_path.read_text(encoding="utf-8")
if "pull-requests: read" not in blocking:
    blocking = blocking.replace("permissions:\n  contents: read\n", "permissions:\n  contents: read\n  pull-requests: read\n", 1)
job = r'''
  memory-retrieval-review:
    name: Memory retrieval promotion review
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: Checkout exact candidate
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
          persist-credentials: false
      - name: Enforce independent current-head approval for claim promotion
        env:
          GH_TOKEN: ${{ github.token }}
          EVENT_NAME: ${{ github.event_name }}
          BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
          PR_NUMBER: ${{ github.event.pull_request.number || '' }}
          REPOSITORY: ${{ github.repository }}
        shell: bash
        run: |
          set -euo pipefail
          root="$RUNNER_TEMP/memory-retrieval-review"
          mkdir -p "$root"
          git show "$BASE_SHA:docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json" > "$root/base-map.json" 2>/dev/null || printf '{}\n' > "$root/base-map.json"
          cp docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json "$root/head-map.json"
          if [ "$EVENT_NAME" = pull_request ]; then
            gh api --paginate --slurp "repos/$REPOSITORY/pulls/$PR_NUMBER/reviews" > "$root/reviews.json"
          else
            printf '[]\n' > "$root/reviews.json"
          fi
          python3 scripts/verify_memory_retrieval_review.py \
            --base-map "$root/base-map.json" --head-map "$root/head-map.json" \
            --event-json "$GITHUB_EVENT_PATH" --reviews-json "$root/reviews.json" \
            --head-sha "$HEAD_SHA" --output "$root/receipt.json"

'''
if "memory-retrieval-review:" not in blocking:
    blocking = blocking.replace("  required:\n", job + "  required:\n", 1)
    blocking = blocking.replace("      - lightweight\n", "      - lightweight\n      - memory-retrieval-review\n", 1)
blocking_path.write_text(blocking, encoding="utf-8")

technical_path = ROOT / "docs/modules/memory.retrieval/TECHNICAL.md"
technical = technical_path.read_text(encoding="utf-8")
marker = "## Production reference set"
if marker not in technical:
    technical += r'''

## Production reference set

The production API, policy order, threats, provider operations and staged rollout are specified in [API.md](API.md), [POLICY_REFERENCE.md](POLICY_REFERENCE.md), [THREAT_MODEL.md](THREAT_MODEL.md), [OPERATIONS.md](OPERATIONS.md) and [CANARY_AND_ROLLBACK.md](CANARY_AND_ROLLBACK.md). The admitted-set and proposition/polarity decisions are recorded in [ADR 0001](ADR/0001-policy-admitted-risk-evaluation.md) and [ADR 0002](ADR/0002-proposition-polarity-contradiction.md). End-to-end measurement and independent acceptance remain separate gates in [SLO_CONTRACT.md](../../../qualification/memory-retrieval/SLO_CONTRACT.md) and [INDEPENDENT_ACCEPTANCE.md](../../../qualification/memory-retrieval/INDEPENDENT_ACCEPTANCE.md).

These references do not change the current claim boundary. Production implementation, product execution, independent acceptance, activation and release remain false until exact-source, synthetic-merge, provider, vector-owner, target-host and independent-review evidence is current.
'''
technical_path.write_text(technical, encoding="utf-8")
