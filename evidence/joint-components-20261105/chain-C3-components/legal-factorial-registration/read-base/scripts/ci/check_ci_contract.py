#!/usr/bin/env python3
"""Check the deliberately fixed hosted-CI structure; this does not execute its lanes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import tomllib

from check_cross_arch_cost import (COST_JOB_TIMEOUT_MINUTES, COST_JOB_OVERHEAD_SECONDS,
                                   cost_job_budget_seconds)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = '.github/workflows/trnm-required-baseline.yml'
CHECKOUT = 'actions/checkout@11d5960a326750d5838078e36cf38b85af677262'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
DOWNLOAD = 'actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0'
SIGNED_STATE_PYTHON = '''      - name: Install isolated signed-state oracle Python environment
        run: |
          python3 -m venv "$RUNNER_TEMP/pon-state-env"
          "$RUNNER_TEMP/pon-state-env/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: -r formal/pon-nakamoto-v1/requirements.txt
          echo "$RUNNER_TEMP/pon-state-env/bin" >> "$GITHUB_PATH"
'''
ZERO_RUN_STEP = '''      - name: Execute native zero-matrix locality costs
        if: always()
        run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_cross_arch_cost.py --arch "${{ matrix.arch }}" --suite zero-locality --zero-version 2
'''
ZERO_COMPARE_STEP = '''      - name: Check zero-matrix streams and exact source identity
        if: always()
        run: python3 scripts/ci/check_cross_arch_cost.py --artifacts "$RUNNER_TEMP/cost-inputs" --expected-source "$TRNM_EXPECTED_SOURCE_SHA" --output "$RUNNER_TEMP/ci-observations/cross-arch-zero-locality-comparison.json" --suite zero-locality --zero-version 2
'''
ONE_ZERO_RUN_STEP = '''      - name: Execute native one-zero rank-one locality costs
        if: always()
        run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_cross_arch_cost.py --arch "${{ matrix.arch }}" --suite one-zero-locality
'''
ONE_ZERO_COMPARE_STEP = '''      - name: Check one-zero rank-one streams and exact source identity
        if: always()
        run: python3 scripts/ci/check_cross_arch_cost.py --artifacts "$RUNNER_TEMP/cost-inputs" --expected-source "$TRNM_EXPECTED_SOURCE_SHA" --output "$RUNNER_TEMP/ci-observations/cross-arch-one-zero-locality-comparison.json" --suite one-zero-locality
'''
MAINTENANCE_RUN_STEP = '''      - name: Execute native fixed maintenance producer and preparation costs
        if: always()
        run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_cross_arch_cost.py --arch "${{ matrix.arch }}" --suite maintenance-paired
'''
MAINTENANCE_COMPARE_STEP = '''      - name: Check fixed maintenance streams and exact source identity
        if: always()
        run: python3 scripts/ci/check_cross_arch_cost.py --artifacts "$RUNNER_TEMP/cost-inputs" --expected-source "$TRNM_EXPECTED_SOURCE_SHA" --output "$RUNNER_TEMP/ci-observations/cross-arch-maintenance-comparison.json" --suite maintenance-paired
'''
REJECTION_RUN_STEP = '''      - name: Execute native legal and late-rejection verifier costs
        if: always()
        run: python3 scripts/pon_work_rejection_report.py --run --out "$TRNM_CI_RECEIPT_DIR/work-rejection"
'''
REJECTION_COMPARE_STEP = '''      - name: Check actual rejection stages and paired native architectures
        if: always()
        run: python3 scripts/pon_work_rejection_report.py --compare "$RUNNER_TEMP/cost-inputs/cost-x64-$TRNM_EXPECTED_SOURCE_SHA-$GITHUB_RUN_ATTEMPT/work-rejection" "$RUNNER_TEMP/cost-inputs/cost-arm64-$TRNM_EXPECTED_SOURCE_SHA-$GITHUB_RUN_ATTEMPT/work-rejection" --expected-source "$TRNM_EXPECTED_SOURCE_SHA" --expected-run "$GITHUB_RUN_ID" --expected-attempt "$GITHUB_RUN_ATTEMPT" --out "$RUNNER_TEMP/ci-observations/work-rejection-comparison"
'''
W1_REUSE_V3_JOB = r'''  cross-arch-w1-reuse-v3:
    name: W1 actual reuse V3 (${{ matrix.arch }}, ${{ matrix.source }})
    if: github.event_name == 'pull_request'
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 155
    strategy:
      fail-fast: false
      matrix:
        arch: [x64, arm64]
        source: [head, prospective-merge]
        include:
          - arch: x64
            runner: ubuntu-24.04
          - arch: arm64
            runner: ubuntu-24.04-arm
    env:
      TRNM_COST_RUNNER_LABEL: ${{ matrix.runner }}
      TRNM_COST_SOURCE_KIND: ${{ matrix.source }}
      TRNM_EXPECTED_SOURCE_SHA: ${{ matrix.source == 'head' && github.event.pull_request.head.sha || github.sha }}
      TRNM_EXPECTED_CANDIDATE_SHA: ${{ github.event.pull_request.head.sha }}
      TRNM_EXPECTED_BASE_SHA: ${{ github.event.pull_request.base.sha }}
    steps:
      - name: Checkout exact candidate
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          ref: ${{ env.TRNM_EXPECTED_SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Verify V3 exact source and ordered merge before execution
        shell: bash
        run: |
          set -euo pipefail
          args=(--kind "$TRNM_COST_SOURCE_KIND" --expected-head "$TRNM_EXPECTED_CANDIDATE_SHA")
          if test "$TRNM_COST_SOURCE_KIND" = prospective-merge; then
            args+=(--expected-base "$TRNM_EXPECTED_BASE_SHA" --expected-merge "$TRNM_EXPECTED_SOURCE_SHA")
          fi
          python3 scripts/ci/verify_ci_source.py "${args[@]}" --output "$RUNNER_TEMP/ci-observations/source-before.json"
      - name: Check original repository boundary before native V3 build
        run: bash scripts/project-preflight.sh --audit
      - name: Set isolated Cargo paths after runner allocation
        shell: bash
        run: |
          set -euo pipefail
          printf 'CARGO_HOME=%s/cargo-%s\n' "$RUNNER_TEMP" "$GITHUB_JOB" >> "$GITHUB_ENV"
          printf 'CARGO_TARGET_DIR=%s/target-%s\n' "$RUNNER_TEMP" "$GITHUB_JOB" >> "$GITHUB_ENV"
          printf 'TRNM_CI_RECEIPT_DIR=%s/ci-observations\n' "$RUNNER_TEMP" >> "$GITHUB_ENV"
      - name: Install pinned native release compiler
        run: rustup toolchain install 1.95.0 --profile minimal
      - name: Install matching native formatter
        run: rustup component add --toolchain 1.95.0 rustfmt
      - name: Execute the complete native W1 actual reuse V3 grid
        run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_w1_reused_cost_v3.py --arch "${{ matrix.arch }}"
      - name: Verify V3 exact source and ordered merge after execution
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          args=(--kind "$TRNM_COST_SOURCE_KIND" --expected-head "$TRNM_EXPECTED_CANDIDATE_SHA")
          if test "$TRNM_COST_SOURCE_KIND" = prospective-merge; then
            args+=(--expected-base "$TRNM_EXPECTED_BASE_SHA" --expected-merge "$TRNM_EXPECTED_SOURCE_SHA")
          fi
          python3 scripts/ci/verify_ci_source.py "${args[@]}" --output "$RUNNER_TEMP/ci-observations/source-after.json"
      - name: Retain V3 costs including all failed observations
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: w1-reuse-v3-${{ matrix.source }}-${{ matrix.arch }}-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/ci-observations/
          if-no-files-found: error
          retention-days: 30
'''
CONTINUITY_BUILD = '    cargo build --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-protocol -p trnm-crypto-primitives -p trnm-mvcc-fee --examples\n'
CONTINUITY_ORIGINAL = '    TRNM_CONTINUITY_BINARY="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuity_vectors")" python3 formal/pon-nakamoto-v1/test_continuity.py -v\n'
CONTINUITY_TRANSITIONS = '    TRNM_CONTINUITY_TRANSITIONS_BINARY="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuity_transition_vectors")" python3 formal/pon-nakamoto-v1/test_continuity_transitions.py -v\n'
PAIRED_WORK_ORACLE = '    TRNM_PAIRED_WORK="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_paired_io")" TRNM_PAIRED_WORK_OUTPUT="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/paired-work" python3 formal/pon-nakamoto-v1/test_paired_work.py -v\n'
ZERO_WORK_ORACLE = '    TRNM_ZERO_WORK="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_zero_io")" TRNM_ZERO_WORK_OUTPUT="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/zero-work" python3 formal/pon-nakamoto-v1/test_zero_work.py -v\n'
MODEL_WINDOW_ORACLE = '    python3 formal/pon-nakamoto-v1/test_model_window_history.py -v\n'
EVALUATION_QUORUM_ORACLE = ('    python3 formal/pon-nakamoto-v1/test_native_evaluation_quorum_oracle.py -v\n'
                          '    python3 formal/pon-nakamoto-v1/native_evaluation_quorum_oracle.py\n')
MODEL_EVOLUTION_ORACLES = ('    python3 formal/pon-nakamoto-v1/test_model_evolution_oracle.py -v\n'
                          '    python3 formal/pon-nakamoto-v1/test_model_task_windows_oracle.py -v\n')
COST_BOUNDARY_READERS = ('    python3 scripts/ci/test_pon_w1_budget_readers.py --raw-dir evidence/pon-upgrade-implementation-20261018/native-rounds/chain-p0-native-54\n'
                         '    python3 scripts/ci/test_pon_public_v3_phase_read.py\n'
                         '    python3 scripts/ci/test_pon_public_v3_policy_read.py\n'
                         '    python3 scripts/ci/test_pon_v3_cookie_cpu_study.py\n'
                         '    python3 scripts/ci/test_run_pon_w1_native_campaign.py\n')
CURRENT_READER_COMMANDS = (
    'python3 scripts/ci/test_pon_w1_cost_matrix_reader.py',
    'python3 scripts/ci/test_pon_w1_reused_cost_reader_v3.py',
    'python3 scripts/ci/test_run_w1_reused_cost_v3.py',
    'python3 scripts/ci/test_pon_public_v3_policy_read.py',
    'python3 scripts/ci/test_llm_cell_handoff_deadline.py',
)
LLM_RUNTIME_TESTS = (
    '    python3 scripts/test_llm_runtime_rss_owner.py\n'
    '    python3 scripts/test_llm_runtime_exit_observation.py\n'
    '    python3 scripts/test_llm_runtime_stop.py\n'
    '    python3 scripts/test_llm_inherited_runtime.py\n'
    '    python3 scripts/test_llm_neural_read_worker.py\n'
    '    python3 scripts/test_llm_python_runtime_contract.py\n'
)
ORIGINAL_CAMPAIGN_READER = r'''    python3 scripts/ci/test_read_original_native_campaign.py \
      --artifact-dir evidence/pon-upgrade-implementation-20261018/native-rounds/chain-pr327-original-campaign-39694587963 \
      --expected-manifest-sha256 12406cc156e57c130fa14af2b50b386031ec3640ce7f0234ed5bc9f0a700aac3 \
      --expected-head 9e705ccf75b7318dcc4bda4815956f58beb10e72 \
      --expected-tree 521ae87a28060d545979069b189eebbc74a71fd8 --retained-subset
'''
NODE_EXAMPLE_BUILD = '    cargo build --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --bins --examples\n'
ACCOUNT_ARCHIVE_ORACLE = ('    python3 formal/pon-nakamoto-v1/test_account_archive_oracle.py -v\n'
                          '    python3 scripts/ci/run_account_archive_conformance.py\n')
ACCOUNT_EXECUTION_ORACLE = ('    python3 formal/pon-nakamoto-v1/test_account_execution_oracle.py -v\n'
                            '    python3 formal/pon-nakamoto-v1/test_state_witness_oracle.py -v\n'
                            '    python3 scripts/ci/run_account_execution_conformance.py\n')
GSC2_SYNTHETIC_ORACLE = '    python3 -B formal/pon-nakamoto-v1/test_gsc2_native_readback_synthetic.py --source-root "$(pwd -P)"\n'
NATIVE_GROWTH_RELEASE_BLOCK = '''      test ! -e "$trnm_native_receipt_root/native-growth-reference-release.log"
      test ! -L "$trnm_native_receipt_root/native-growth-reference-release.log"
      test ! -e "$trnm_native_receipt_root/native-growth-reference"
      test ! -L "$trnm_native_receipt_root/native-growth-reference"
      TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY="$trnm_native_receipt_root/native-growth-reference" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-growth-reference-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-growth-reference-release.log" --test store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen
      test ! -e "$trnm_native_receipt_root/native-growth-reference/readback.json"
      test ! -L "$trnm_native_receipt_root/native-growth-reference/readback.json"
      python3 -B formal/pon-nakamoto-v1/check_gsc2_native_readback.py --artifact-dir "$trnm_native_receipt_root/native-growth-reference" --source-root "$(pwd -P)" --minimum-accounts 65537 > "$trnm_native_receipt_root/native-growth-reference/readback.json"
'''
NATIVE_GROWTH_V2_RELEASE_BLOCK = '''      test ! -e "$trnm_native_receipt_root/native-growth-v2-release.log"
      test ! -L "$trnm_native_receipt_root/native-growth-v2-release.log"
      test ! -e "$trnm_native_receipt_root/native-growth-v2"
      test ! -L "$trnm_native_receipt_root/native-growth-v2"
      TRNM_NATIVE_GROWTH_V2_EXPORT_DIR="$trnm_native_receipt_root/native-growth-v2" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-growth-v2-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-growth-v2-release.log" --test store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen
      test -s "$trnm_native_receipt_root/native-growth-v2/native.json"
      test ! -L "$trnm_native_receipt_root/native-growth-v2/native.json"
'''
RUST_ALL_TARGETS = 'cargo test --locked --manifest-path trillionnium/Cargo.toml --workspace --all-targets --all-features'
RUST_DOCS = '    cargo test --locked --manifest-path trillionnium/Cargo.toml --workspace --doc --all-features\n'
RUST_CLIPPY = '    cargo clippy --locked --manifest-path trillionnium/Cargo.toml --workspace --all-targets --all-features -- -D warnings\n'
MODEL_OBSERVATION_BLOCK = '''    (
      trnm_model_receipt_root="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}"
      mkdir -p "$trnm_model_receipt_root"
      export TRNM_MODEL_COMPOSITION_VECTORS="$trnm_model_receipt_root/model-composition"
      test ! -e "$TRNM_MODEL_COMPOSITION_VECTORS"
      test ! -L "$TRNM_MODEL_COMPOSITION_VECTORS"
      mkdir "$TRNM_MODEL_COMPOSITION_VECTORS"
      export TRNM_MODEL_COMPOSITION_RUN_ID="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
      test -n "$TRNM_MODEL_COMPOSITION_RUN_ID"
      printf 'model-composition directory=%s run_id=%s\\n' "$TRNM_MODEL_COMPOSITION_VECTORS" "$TRNM_MODEL_COMPOSITION_RUN_ID"
      export TRNM_AUTHENTICATED_STATE_VECTORS="$trnm_model_receipt_root/authenticated-state/native.json"
      test ! -e "$trnm_model_receipt_root/authenticated-state"
      test ! -L "$trnm_model_receipt_root/authenticated-state"
      mkdir "$trnm_model_receipt_root/authenticated-state"
      export TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR="$trnm_model_receipt_root/native-authenticated-state"
      test ! -e "$TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR"
      test ! -L "$TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR"
      export TRNM_AUTHENTICATED_MIGRATION_EXPORT="$trnm_model_receipt_root/authenticated-migration"
      test ! -e "$TRNM_AUTHENTICATED_MIGRATION_EXPORT"
      test ! -L "$TRNM_AUTHENTICATED_MIGRATION_EXPORT"
      export TRNM_ACCOUNT_MULTIPROOF_VECTORS="$trnm_model_receipt_root/account-multiproof/native.json"
      test ! -e "$trnm_model_receipt_root/account-multiproof"
      test ! -L "$trnm_model_receipt_root/account-multiproof"
      mkdir "$trnm_model_receipt_root/account-multiproof"
      export TRNM_OBLIGATION_RANGE_VECTORS="$trnm_model_receipt_root/obligation-range/native.json"
      test ! -e "$trnm_model_receipt_root/obligation-range"
      test ! -L "$trnm_model_receipt_root/obligation-range"
      mkdir "$trnm_model_receipt_root/obligation-range"
      export TRNM_ZERO_PAIRED_PREFIX_OUTPUT="$trnm_model_receipt_root/zero-paired-prefix"
      test ! -e "$TRNM_ZERO_PAIRED_PREFIX_OUTPUT"
      test ! -L "$TRNM_ZERO_PAIRED_PREFIX_OUTPUT"
      export TRNM_DAA_EVIDENCE_DIR="$trnm_model_receipt_root/daa-bounds"
      test ! -e "$TRNM_DAA_EVIDENCE_DIR"
      test ! -L "$TRNM_DAA_EVIDENCE_DIR"
      test ! -e "$trnm_model_receipt_root/workspace-tests.log"
      test ! -L "$trnm_model_receipt_root/workspace-tests.log"
      cargo test --locked --manifest-path trillionnium/Cargo.toml --workspace --all-targets --all-features 2>&1 | tee "$trnm_model_receipt_root/workspace-tests.log"
      unset TRNM_ZERO_PAIRED_PREFIX_OUTPUT
      python3 scripts/pon_daa_schedule_reader.py --raw-dir "$TRNM_DAA_EVIDENCE_DIR" --expected-report-sha256 "$(sha256sum "$TRNM_DAA_EVIDENCE_DIR/daa-bounds.json" | cut -d ' ' -f 1)" > "$trnm_model_receipt_root/daa-bounds-python.json"
      python3 scripts/ci/test_pon_daa_schedule_reader.py --raw-dir "$TRNM_DAA_EVIDENCE_DIR"
      unset TRNM_DAA_EVIDENCE_DIR
      python3 formal/pon-nakamoto-v1/test_zero_work.py --verify-prefix-export "$trnm_model_receipt_root/zero-paired-prefix" --output "$trnm_model_receipt_root/zero-paired-prefix-python"
      python3 formal/pon-nakamoto-v1/test_model_composition_oracle.py -v
      python3 formal/pon-nakamoto-v1/test_model_composition.py -v
      python3 formal/pon-nakamoto-v1/test_authenticated_state_archive_oracle.py -v
      python3 formal/pon-nakamoto-v1/authenticated_state_archive_oracle.py "$TRNM_AUTHENTICATED_STATE_VECTORS" "$trnm_model_receipt_root/authenticated-state/native.sqlite" --output "$trnm_model_receipt_root/authenticated-state/oracle.json"
      python3 formal/pon-nakamoto-v1/test_native_authenticated_storage_oracle.py -v
      python3 formal/pon-nakamoto-v1/native_authenticated_storage_oracle.py "$TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR/native.json" "$TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR/native.sqlite" --output "$TRNM_NATIVE_AUTHENTICATED_STATE_EXPORT_DIR/oracle.json"
      python3 formal/pon-nakamoto-v1/native_authenticated_storage_oracle.py "$TRNM_AUTHENTICATED_MIGRATION_EXPORT/native.json" "$TRNM_AUTHENTICATED_MIGRATION_EXPORT/native.sqlite" --migration-source "$TRNM_AUTHENTICATED_MIGRATION_EXPORT/source.sqlite" --output "$TRNM_AUTHENTICATED_MIGRATION_EXPORT/oracle.json"
      python3 formal/pon-nakamoto-v1/test_account_multiproof_oracle.py -v
      python3 formal/pon-nakamoto-v1/account_multiproof_oracle.py "$TRNM_ACCOUNT_MULTIPROOF_VECTORS" --output "$trnm_model_receipt_root/account-multiproof/oracle.json"
      python3 formal/pon-nakamoto-v1/test_obligation_range_oracle.py -v
      python3 formal/pon-nakamoto-v1/obligation_range_oracle.py "$TRNM_OBLIGATION_RANGE_VECTORS" --output "$trnm_model_receipt_root/obligation-range/oracle.json"
    )
'''
NATIVE_RELEASE_BLOCK = '''    (
      trnm_native_receipt_root="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}"
      mkdir -p "$trnm_native_receipt_root"
      test ! -e "$trnm_native_receipt_root/native-capacity-release.log"
      test ! -L "$trnm_native_receipt_root/native-capacity-release.log"
      cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-capacity-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-capacity-release.log" --test account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover
''' + NATIVE_GROWTH_RELEASE_BLOCK + NATIVE_GROWTH_V2_RELEASE_BLOCK + '''\
      test ! -e "$trnm_native_receipt_root/native-account-verification-cost"
      test ! -L "$trnm_native_receipt_root/native-account-verification-cost"
      test ! -e "$trnm_native_receipt_root/native-account-verification-cost.log"
      test ! -L "$trnm_native_receipt_root/native-account-verification-cost.log"
      TRNM_NATIVE_ACCOUNT_VERIFY_COST_DIRECTORY="$trnm_native_receipt_root/native-account-verification-cost" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib account_archive_prototype::native_primitive_tests::native_complete_account_verification_cost -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-account-verification-cost.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-account-verification-cost.log" --test account_archive_prototype::native_primitive_tests::native_complete_account_verification_cost
    )
'''

# Freeze the complete straight-line lane independently of the file being checked.
# Presence/count checks alone also match commands skipped or swallowed by shell
# control flow. Keep their specific diagnostics before the full-lane comparison.
PROTOCOL_CONTRACT_BLOCK = '''    python3 scripts/ci/run_from_zero_host.py -- python3 scripts/ci/run_from_zero_native.py --out "${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/from-zero-native"
    cargo test --locked --manifest-path trillionnium/Cargo.toml -p trnm-crypto-primitives -p trnm-checkpoint-types -p trnm-verification-profiles --all-targets --all-features
    cargo test --locked --manifest-path trillionnium/Cargo.toml -p trnm-protocol --all-targets --all-features
    cargo build --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-protocol -p trnm-crypto-primitives -p trnm-mvcc-fee --examples
    TRNM_CONTINUITY_BINARY="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuity_vectors")" python3 formal/pon-nakamoto-v1/test_continuity.py -v
    TRNM_CONTINUITY_TRANSITIONS_BINARY="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuity_transition_vectors")" python3 formal/pon-nakamoto-v1/test_continuity_transitions.py -v
    TRNM_PAIRED_WORK="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_paired_io")" TRNM_PAIRED_WORK_OUTPUT="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/paired-work" python3 formal/pon-nakamoto-v1/test_paired_work.py -v
    TRNM_ZERO_WORK="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_zero_io")" TRNM_ZERO_WORK_OUTPUT="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/zero-work" python3 formal/pon-nakamoto-v1/test_zero_work.py -v
    TRNM_GROUPED_NATIVE="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_routed_int257_grouped")" python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_grouped*.py' -v
    cargo test --locked --manifest-path trillionnium/Cargo.toml -p trnm-transport proof_admission --all-targets
    python3 formal/pon-nakamoto-v1/test_contracts.py
    python3 formal/pon-nakamoto-v1/test_invariants.py
    cargo fetch --locked --manifest-path trillionnium/Cargo.toml
    cargo build --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --bins --examples
    python3 formal/pon-nakamoto-v1/test_account_archive_oracle.py -v
    python3 scripts/ci/run_account_archive_conformance.py
    python3 formal/pon-nakamoto-v1/test_account_execution_oracle.py -v
    python3 formal/pon-nakamoto-v1/test_state_witness_oracle.py -v
    python3 scripts/ci/run_account_execution_conformance.py
    python3 -B formal/pon-nakamoto-v1/test_gsc2_native_readback_synthetic.py --source-root "$(pwd -P)"
    cargo test --offline --locked --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --test qualified_tasks --test protected_ingress --test task_lifecycle --test task_lifecycle_v3 --test task_lifecycle_v4 --test public_evaluation --test public_intake_v2 --test public_cli --test local_mempool --test pool_mining --test public_pool_v3 --test public_pool_cli --test public_v3_observer --test pinned_peer_polling --test ancestry_long_sync --test distributed_roles
    TRNM_DISTRIBUTED_TEST_BINARY="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/distributed_pipeline" TRNM_DISTRIBUTED_TEST_OUTPUT="${RUNNER_TEMP:-/tmp}/trnm-distributed-conformance-$$" cargo test --offline --locked --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --test distributed_roles -- --ignored --test-threads=1
    python3 scripts/run_public_v3_service_campaign.py --out "${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/public-v3-service"
    python3 scripts/test_llm_runtime_pilot.py
    python3 scripts/test_llm_parent_material.py
    python3 scripts/test_llm_runtime_parent_step.py
    python3 scripts/test_llm_runtime_rss_owner.py
    python3 scripts/test_llm_runtime_exit_observation.py
    python3 scripts/test_llm_runtime_stop.py
    python3 scripts/test_llm_inherited_runtime.py
    python3 scripts/test_llm_neural_read_worker.py
    python3 scripts/test_llm_python_runtime_contract.py
    python3 formal/pon-nakamoto-v1/test_reward_budget_oracle.py
    python3 formal/pon-nakamoto-v1/test_model_attribution.py
    python3 formal/pon-nakamoto-v1/test_model_evolution_oracle.py -v
    python3 formal/pon-nakamoto-v1/test_model_task_windows_oracle.py -v
    python3 formal/pon-nakamoto-v1/test_work_utility.py
    python3 formal/pon-nakamoto-v1/test_shared_cell_operator_v1.py
    python3 scripts/ci/test_shared_material_cost_v2.py
    python3 scripts/ci/test_shared_material_security_v1.py
    python3 scripts/ci/test_shared_material_campaign_v2.py
    python3 formal/pon-nakamoto-v1/test_public_evaluation_lifecycle.py
    python3 formal/pon-nakamoto-v1/test_llm_adapter_contract.py
    python3 formal/pon-nakamoto-v1/test_model_acceptance.py
    python3 formal/pon-nakamoto-v1/test_model_window_history.py -v
    python3 formal/pon-nakamoto-v1/test_native_evaluation_quorum_oracle.py -v
    python3 formal/pon-nakamoto-v1/native_evaluation_quorum_oracle.py
    "${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/continuous_pipeline" "${RUNNER_TEMP:-/tmp}/trnm-pipeline-smoke-$$" 2 4 0 growth protected
    python3 formal/pon-nakamoto-v1/test_evaluation_round.py
    python3 formal/pon-nakamoto-v1/test_evaluation.py
    python3 formal/pon-nakamoto-v1/test_evaluation_bundle.py
    python3 formal/pon-nakamoto-v1/test_artifacts.py
    python3 formal/pon-nakamoto-v1/test_inference_receipt.py
    python3 formal/pon-nakamoto-v1/test_bounded_process.py
    python3 formal/pon-nakamoto-v1/test_kernel_process.py
    python3 formal/pon-nakamoto-v1/test_client_confirmation.py
    python3 formal/pon-nakamoto-v1/test_native_session.py
    python3 formal/pon-nakamoto-v1/test_work_precheck.py
    TRNM_NATIVE_WORK="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_work_io" TRNM_NATIVE_SESSION="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_execute_session" TRNM_EXECUTION_WORKERS=8 python3 formal/pon-nakamoto-v1/test_client_confirmation.py
    TRNM_NATIVE_WORK="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_work_io" TRNM_NATIVE_SESSION="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_execute_session" TRNM_EXECUTION_WORKERS=8 python3 formal/pon-nakamoto-v1/test_contracts.py
    TRNM_NATIVE_WORK="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_work_io" TRNM_NATIVE_SESSION="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_execute_session" TRNM_EXECUTION_WORKERS=8 python3 formal/pon-nakamoto-v1/test_invariants.py
    TRNM_NATIVE_WORK="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_work_io" TRNM_NATIVE_EXECUTOR="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_execute" TRNM_EXECUTION_WORKERS=8 python3 formal/pon-nakamoto-v1/test_client_confirmation.py
    python3 formal/pon-nakamoto-v1/test_model_contract.py
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_useful_cell_numeric_v1.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_useful_cell_relation_v1.py' -v
    python3 formal/pon-nakamoto-v1/test_work_backend.py
    python3 formal/pon-nakamoto-v1/test_strict_signature.py
    TRNM_NATIVE_MODE=release python3 formal/pon-nakamoto-v1/test_native_execution.py
    TRNM_NATIVE_EXECUTOR="${CARGO_TARGET_DIR:-trillionnium/target}/release/examples/pon_execute" TRNM_EXECUTION_WORKERS=8 python3 formal/pon-nakamoto-v1/test_contracts.py
    TRNM_NATIVE_MODE=release python3 formal/pon-nakamoto-v1/test_interop.py
    TRNM_NATIVE_MODE=release python3 scripts/ci/test_pon_accepted_block.py
    cargo build --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-data-availability --bin trnm-cell
    trnm_cell_handoff_binary="$(realpath -e "${CARGO_TARGET_DIR:-trillionnium/target}/release/trnm-cell")"
    test -x "$trnm_cell_handoff_binary"
    TRNM_CELL_BIN="$trnm_cell_handoff_binary" python3 scripts/ci/test_llm_cell_host_handoff.py -v
'''


def code_lines(text: str) -> list[str]:
    """The fixed lane permits whole-line comments, not alternate shell control flow."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def check_independent_conformance(script: str, required: set[str]) -> None:
    require(script.startswith('#!/usr/bin/env bash\nset -euo pipefail\n'),
            'lane execution must propagate actual failures')
    pairs = re.findall(r'(?ms)^  ([a-z][a-z0-9-]*)\)\n(.*?)(?=^    ;;$)', script)
    lanes = dict(pairs)
    require(len(pairs) == len(lanes) and set(lanes) == required, 'exact five executable lane selectors')
    parent_material = '    python3 scripts/test_llm_parent_material.py\n'
    parent_step = '    python3 scripts/test_llm_runtime_parent_step.py\n'
    for command in (parent_material, parent_step):
        require(command in lanes['protocol-contract'] and script.count(command) == 1,
                'parent material and parent-step byte checks must execute exactly once in protocol-contract')
    for command in CURRENT_READER_COMMANDS:
        require(code_lines(lanes['repository-truth']).count(command) == 1
                and code_lines(script).count(command) == 1,
                'current cost, policy and cell deadline reader controls must execute exactly once in repository-truth')
    runtime_pilot = '    python3 scripts/test_llm_runtime_pilot.py\n'
    require(runtime_pilot + parent_material + parent_step + LLM_RUNTIME_TESTS in lanes['protocol-contract']
            and all(code_lines(script).count(command) == 1
                    for command in code_lines(LLM_RUNTIME_TESTS)),
            'runtime owner, exit, inheritance and neural worker controls must retain their straight-line command sequence exactly once after pilot, parent material and parent step in protocol-contract')
    reward_budgets = '    python3 formal/pon-nakamoto-v1/test_reward_budget_oracle.py\n'
    require(reward_budgets in lanes['protocol-contract'] and script.count(reward_budgets) == 1,
            'five-lane reward budget controls must execute exactly once in protocol-contract')
    require(code_lines(lanes['protocol-contract']).count(GSC2_SYNTHETIC_ORACLE.strip()) == 1
            and code_lines(script).count(GSC2_SYNTHETIC_ORACLE.strip()) == 1,
            'GSC2 synthetic readback counterexamples must execute exactly once in protocol-contract with the current source root')
    continuity = CONTINUITY_BUILD + CONTINUITY_ORIGINAL + CONTINUITY_TRANSITIONS + PAIRED_WORK_ORACLE + ZERO_WORK_ORACLE
    require(continuity in lanes['protocol-contract'] and script.count(CONTINUITY_ORIGINAL) == 1
            and script.count(CONTINUITY_TRANSITIONS) == 1,
            'continuity and paired-work oracles must execute in protocol-contract after their actual release build')
    require(script.count(PAIRED_WORK_ORACLE) == 1,
            'one native paired-work byte comparison must retain its fresh current-lane output')
    require(script.count(ZERO_WORK_ORACLE) == 1,
            'one native zero-work byte comparison must retain its fresh current-lane output after its release build')
    require(MODEL_WINDOW_ORACLE in lanes['protocol-contract'] and script.count(MODEL_WINDOW_ORACLE) == 1,
            'model-window history arithmetic and frozen evidence checks must execute once in protocol-contract')
    require(MODEL_WINDOW_ORACLE + EVALUATION_QUORUM_ORACLE in lanes['protocol-contract'] and
            all(script.count(command) == 1 for command in EVALUATION_QUORUM_ORACLE.splitlines(keepends=True)),
            'evaluation quorum oracle and exact retained vectors must execute once in protocol-contract without rewriting fixtures')
    for block, lane, label in [(MODEL_EVOLUTION_ORACLES, 'protocol-contract', 'model evolution and task-window oracles'),
                               (COST_BOUNDARY_READERS, 'repository-truth', 'work-cost and DAA reader controls'),
                               (ORIGINAL_CAMPAIGN_READER, 'repository-truth', 'original campaign source-pinned reader controls')]:
        require(block in lanes[lane] and all(script.count(command) == 1 for command in block.splitlines(keepends=True)),
                label + ' must execute once in their original lane')
    require(NODE_EXAMPLE_BUILD + ACCOUNT_ARCHIVE_ORACLE in lanes['protocol-contract'] and
            script.count(ACCOUNT_ARCHIVE_ORACLE) == 1,
            'native archive vectors and the independent read-only oracle must execute after their actual release build')
    require(NODE_EXAMPLE_BUILD + ACCOUNT_ARCHIVE_ORACLE + ACCOUNT_EXECUTION_ORACLE in lanes['protocol-contract'] and
            script.count(ACCOUNT_EXECUTION_ORACLE) == 1,
            'native account execution, complete state witness and independent JSON oracles must execute once after the actual Node release build')
    require(NODE_EXAMPLE_BUILD + ACCOUNT_ARCHIVE_ORACLE + ACCOUNT_EXECUTION_ORACLE +
            GSC2_SYNTHETIC_ORACLE in lanes['protocol-contract'],
            'GSC2 synthetic counterexamples must follow the unchanged native archive/execution oracle sequence')
    expected = ('    cargo fmt --manifest-path trillionnium/Cargo.toml --all -- --check\n'
                '    python3 scripts/ci/run_supply_chain.py\n' + MODEL_OBSERVATION_BLOCK +
                NATIVE_RELEASE_BLOCK + RUST_DOCS + RUST_CLIPPY)
    require(code_lines(lanes['rust-baseline']) == code_lines(expected),
            'one actual workspace test must collect fresh native observations, check every independent reader, explicitly execute all four release controls, then run docs/Clippy outside exports')
    require(NATIVE_GROWTH_RELEASE_BLOCK in lanes['rust-baseline'] and
            all(code_lines(script).count(command) == 1
                for command in code_lines(NATIVE_GROWTH_RELEASE_BLOCK)),
            'native 65537-account growth must execute once in rust-baseline with a fresh export, exact nonempty release test and independent SQLite readback')
    require(script.count('TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY') ==
            NATIVE_GROWTH_RELEASE_BLOCK.count('TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY'),
            'native growth export selector must remain in its one release/readback block')
    require(NATIVE_GROWTH_V2_RELEASE_BLOCK in lanes['rust-baseline'] and
            all(code_lines(script).count(command) == 1
                for command in code_lines(NATIVE_GROWTH_V2_RELEASE_BLOCK)),
            'bounded native growth must execute once in rust-baseline with its fresh export and exact nonempty release test')
    require(script.count('TRNM_NATIVE_GROWTH_V2_EXPORT_DIR') ==
            NATIVE_GROWTH_V2_RELEASE_BLOCK.count('TRNM_NATIVE_GROWTH_V2_EXPORT_DIR'),
            'bounded native growth export selector must remain in its one release block')
    require(script.count(RUST_ALL_TARGETS) == 1, 'the full workspace observation suite must execute exactly once')
    for selector in ['TRNM_MODEL_COMPOSITION_VECTORS', 'TRNM_MODEL_COMPOSITION_RUN_ID',
                     'TRNM_OBLIGATION_RANGE_VECTORS', 'TRNM_ZERO_PAIRED_PREFIX_OUTPUT',
                     'TRNM_DAA_EVIDENCE_DIR']:
        require(script.count(selector) == MODEL_OBSERVATION_BLOCK.count(selector),
                'native observation selectors must remain inside the single test/oracle subshell')
    require(script.count(NATIVE_RELEASE_BLOCK) == 1,
            'full-capacity, reference-growth, bounded-growth and account-verification release controls must execute once sequentially')
    require(code_lines(lanes['protocol-contract']) == code_lines(PROTOCOL_CONTRACT_BLOCK),
            'protocol-contract must retain its complete straight-line command sequence without shell control flow that skips tests or swallows failures')
    dispatch_prefix = ('#!/usr/bin/env bash\nset -euo pipefail\n'
                       'export RUST_TEST_THREADS="${RUST_TEST_THREADS:-1}"\n'
                       'case "${1:?required job}" in\n')
    dispatch_suffix = "  *) printf '%s\\n' 'unknown CI job' >&2; exit 2 ;;\nesac\n"
    reconstructed = dispatch_prefix + ''.join(
        '  ' + name + ')\n' + block + '    ;;\n' for name, block in pairs) + dispatch_suffix
    require(script == reconstructed,
            'straight-line lane dispatch must not wrap or swallow the selected lane')


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError('CI contract: ' + message)


def check_from_zero_host_call(text: str, exact_block: str) -> None:
    require(text.count('python3 scripts/ci/run_from_zero_native.py') == 1
            and text.count('python3 scripts/ci/run_from_zero_host.py') == 1
            and exact_block in text,
            'one unchanged from-zero argv must run through the original fixed Host parent')


HISTORY_HOST_STEPS = '''      - name: Build the original long-history test separately from measurement
        id: history_build
        if: ${{ !cancelled() && steps.source.outcome == 'success' && steps.toolchain.outcome == 'success' && matrix.campaign == 'history' }}
        run: python3 scripts/ci/run_history_native.py --prepare --out "$TRNM_CI_RECEIPT_DIR/history-native"
      - name: Execute 4105 real work blocks and paid public full sync
        if: ${{ !cancelled() && steps.history_build.outcome == 'success' && matrix.campaign == 'history' }}
        run: python3 scripts/ci/run_from_zero_host.py -- python3 scripts/ci/run_history_native.py --out "$TRNM_CI_RECEIPT_DIR/history-native"
'''
HISTORY_EXPECTED_SOURCE = (
    "      TRNM_EXPECTED_SOURCE_SHA: ${{ matrix.source == 'head' && "
    "github.event.pull_request.head.sha || github.sha }}\n")


def check_history_host_call(text: str) -> str:
    require(text.count(HISTORY_HOST_STEPS) == 1
            and text.count('python3 scripts/ci/run_history_native.py') == 2,
            'history retains one exact build and one whole native test under the fixed Host')
    require(text.count(HISTORY_EXPECTED_SOURCE) == 1
            and text.count('    timeout-minutes: 180\n') == 1,
            'history retains the event-selected source and original 180-minute job budget')
    # Remove only the two exact checked history steps. The original from-zero
    # call must still occur exactly once; no arbitrary second Host command is allowed.
    return text.replace(HISTORY_HOST_STEPS, '')


def check_from_zero_host_callsites(root: Path) -> None:
    command = ('python3 scripts/ci/run_from_zero_host.py -- '
               'python3 scripts/ci/run_from_zero_native.py --out ')
    workflow_command = '        run: ' + command + '"$TRNM_CI_RECEIPT_DIR/from-zero-native"\n'
    check_from_zero_host_call((root / 'scripts/ci/ci_job.sh').read_text(),
        '  protocol-contract)\n    ' + command
        + '"${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/from-zero-native"\n')
    check_from_zero_host_call((root / '.github/workflows/trnm-required-baseline.yml').read_text(),
        '      - name: Execute exact native from-zero service controls\n'
        '        if: always()\n' + workflow_command)
    priority = check_history_host_call((root / '.github/workflows/pon-priority-acceptance.yml').read_text())
    check_from_zero_host_call(priority,
        '      - name: Execute original release from-zero controls\n'
        "        if: ${{ !cancelled() && steps.source.outcome == 'success' && "
        "steps.toolchain.outcome == 'success' && matrix.campaign == 'service-model' }}\n"
        + workflow_command)
    require('        run: python3 scripts/ci/test_from_zero_host_ci.py\n' in
            (root / '.github/workflows/trnm-required-baseline.yml').read_text(),
            'required repository-truth retains public Host CI refusal controls')


def check_w1_reuse_v3(block: str) -> None:
    # This explicit observation lane cannot replace any retained work/cost gate.
    # Exact steps bind the original runner, budgets and fail-closed raw reader.
    require(block == W1_REUSE_V3_JOB.split("\n", 1)[1],
            'four exact W1 V3 head/merge native lanes with retained failure artifacts')


def check_inline_source_pins(root: Path) -> int:
    """Check existing literal blob guards before CI spends a native build.

    This does not add pins or authenticate source execution. The workflow's
    original guard remains authoritative; a reviewed source edit must update
    its corresponding literal rather than silently skipping the guard.
    """
    count = 0
    pattern = re.compile(r'test "\$\(git hash-object ([A-Za-z0-9_./-]+)\)" = ([0-9a-f]{40})')
    for workflow in sorted((root / '.github/workflows').glob('*.yml')):
        for line_number, line in enumerate(workflow.read_text().splitlines(), 1):
            line = line.strip()
            if line.startswith('#') or 'git hash-object' not in line:
                continue
            context = f'{workflow.relative_to(root)}:{line_number}'
            match = pattern.fullmatch(line)
            require(match is not None, 'unsupported inline source guard: ' + context)
            path, expected = match.groups()
            require(not path.startswith('/') and all(part not in ('', '.', '..')
                    for part in path.split('/')), 'noncanonical inline source path: ' + context)
            source = root / path
            require(source.is_file() and not source.is_symlink(),
                    'missing regular inline source: ' + context)
            raw = source.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw,
                                  usedforsecurity=False).hexdigest()
            require(actual == expected, f'inline source pin differs: {context}: {path}: '
                    f'expected {expected}, observed {actual}')
            count += 1
    return count


def validate(root: Path = ROOT) -> dict:
    inline_source_pins = check_inline_source_pins(root)
    check_from_zero_host_callsites(root)
    text = (root / WORKFLOW).read_text()
    body = text.split('\njobs:\n', 1)
    require(len(body) == 2, 'one explicit jobs mapping required')
    pairs = re.findall(r'(?ms)^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)', body[1])
    jobs = dict(pairs)
    required = json.loads((root / 'config/repository-policy-v1.json').read_text())['required_check_names']
    require(len(jobs) == len(pairs) and set(jobs) == set(required) |
            {'prospective-merge', 'cross-arch-cost', 'cross-arch-cost-consistency',
             'rust-baseline-shards', 'prospective-rust-shards', 'prospective-rust-baseline',
             'cross-arch-w1-reuse-v3'},
            'required head jobs, separate merge matrix and actual cross-architecture costs must remain explicit')
    require('continue-on-error' not in text and 'pull_request_target' not in text and
            'contents: write' not in text and 'self-hosted' not in text,
            'untrusted source may not gain privilege or discard failures')
    require('  contents: read\n' in text, 'read-only repository permission')
    for name, block in jobs.items():
        expected_runner = '${{ matrix.runner }}' if name in {'cross-arch-cost', 'cross-arch-w1-reuse-v3'} else 'ubuntu-24.04'
        require('    runs-on: ' + expected_runner + '\n' in block, name + ' hosted runner')
        require('uses: ' + CHECKOUT in block and '          fetch-depth: 0\n' in block and
                '          persist-credentials: false\n' in block and
                '          ref: ${{ env.TRNM_EXPECTED_SOURCE_SHA }}\n' in block,
                name + ' immutable credential-free checkout')
        if name not in {'cross-arch-cost-consistency', 'rust-baseline', 'prospective-rust-baseline'}:
            require(block.count('name: Set isolated Cargo paths after runner allocation') == 1,
                    name + ' runner-stage isolation')
            require(block.count('"$RUNNER_TEMP" "$GITHUB_JOB" >> "$GITHUB_ENV"') == 2,
                    name + ' isolated Cargo directories')
        require('uses: ' + UPLOAD in block and '        if: always()\n' in block and
                '          if-no-files-found: error\n' in block,
                name + ' retained observations on success and failure')
        if name not in {'prospective-merge', 'prospective-rust-shards', 'prospective-rust-baseline',
                        'cross-arch-w1-reuse-v3'}:
            require(block.count('verify_ci_source.py --kind head --expected-head "$TRNM_EXPECTED_SOURCE_SHA"') == 2,
                    name + ' exact head before and after execution')
        if name in set(required) - {'rust-baseline'}:
            require(not re.search(r'^    if:', block, re.M), name + ' cannot be conditionally skipped')
            require('        run: bash scripts/ci/ci_job.sh ' + name + '\n' in block,
                    name + ' must execute its actual lane')
    check_w1_reuse_v3(jobs['cross-arch-w1-reuse-v3'])
    costs = jobs['cross-arch-cost']
    require(not re.search(r'^    if:', costs, re.M), 'native architecture execution cannot be skipped')
    require(f'    timeout-minutes: {COST_JOB_TIMEOUT_MINUTES}\n' in costs and
            '      fail-fast: false\n' in costs,
            'architecture job must cover four generation suites and the separate rejection experiment')
    require(COST_JOB_OVERHEAD_SECONDS >= 27 * 60 and
            COST_JOB_TIMEOUT_MINUTES * 60 >= cost_job_budget_seconds(),
            'all generation/rejection capture budgets, termination grace and setup/source/artifact margin must fit')
    require('''        include:
          - arch: x64
            runner: ubuntu-24.04
          - arch: arm64
            runner: ubuntu-24.04-arm
''' in costs, 'two explicit native hosted runner architectures required')
    require('      TRNM_COST_RUNNER_LABEL: ${{ matrix.runner }}\n' in costs and
            '        run: rustup toolchain install 1.95.0 --profile minimal\n' in costs,
            'observed runner label and pinned native release compiler required')
    require('        run: env -u CARGO_INCREMENTAL python3 scripts/ci/run_cross_arch_cost.py --arch "${{ matrix.arch }}"\n' in costs,
            'architecture names are not a substitute for native cost execution')
    require(ZERO_RUN_STEP in costs and text.count(ZERO_RUN_STEP) == 1,
            'separate zero locality native execution must run once in each existing architecture job, including after reused failure')
    require(ZERO_RUN_STEP + ONE_ZERO_RUN_STEP in costs and text.count(ONE_ZERO_RUN_STEP) == 1,
            'one-zero locality must run once after the zero suite, including after either preceding suite failed')
    require(ONE_ZERO_RUN_STEP + MAINTENANCE_RUN_STEP in costs and text.count(MAINTENANCE_RUN_STEP) == 1,
            'fixed maintenance must execute once after the three retained suites including their failure paths')
    require(MAINTENANCE_RUN_STEP + REJECTION_RUN_STEP in costs and text.count(REJECTION_RUN_STEP) == 1,
            'actual legal/Transcript/Product measurements must execute after retained generation suites even on failure')
    require('          name: cost-${{ matrix.arch }}-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}\n' in costs,
            'architecture artifacts must be bound to the same head and attempt')
    comparison = jobs['cross-arch-cost-consistency']
    require('    needs: cross-arch-cost\n    if: always()\n' in comparison,
            'comparison must inspect both success and failure outcomes')
    require('uses: ' + DOWNLOAD in comparison and
            '          pattern: cost-*-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}\n' in comparison and
            '          merge-multiple: false\n' in comparison,
            'comparison must retrieve both actual current-run artifacts without overwriting either')
    require('        run: python3 scripts/ci/check_cross_arch_cost.py --artifacts "$RUNNER_TEMP/cost-inputs" '
            '--expected-source "$TRNM_EXPECTED_SOURCE_SHA" --output '
            '"$RUNNER_TEMP/ci-observations/cross-arch-comparison.json"\n' in comparison,
            'same-source cross-architecture streams must be checked from actual artifacts')
    require(ZERO_COMPARE_STEP in comparison and text.count(ZERO_COMPARE_STEP) == 1,
            'separate zero locality comparison must inspect actual current-run artifacts even after reused comparison failure')
    require(ZERO_COMPARE_STEP + ONE_ZERO_COMPARE_STEP in comparison and text.count(ONE_ZERO_COMPARE_STEP) == 1,
            'one-zero comparison must inspect its own current-run artifacts after the zero comparison even on earlier failure')
    require(ONE_ZERO_COMPARE_STEP + MAINTENANCE_COMPARE_STEP in comparison and
            text.count(MAINTENANCE_COMPARE_STEP) == 1,
            'fixed maintenance comparison must inspect its separate current-run artifacts after earlier failure')
    require(MAINTENANCE_COMPARE_STEP + REJECTION_COMPARE_STEP in comparison and
            text.count(REJECTION_COMPARE_STEP) == 1,
            'actual rejection comparison must bind both native architectures to this head/run/attempt even on earlier failure')
    merge = jobs['prospective-merge']
    require(re.findall(r'^    timeout-minutes: (.+)$', jobs['rust-baseline'], re.M) == ['180'],
            'the complete head Rust suite requires its explicit 180-minute job budget')
    require(re.findall(r'^    timeout-minutes: (.+)$', merge, re.M) ==
            ["${{ matrix.lane == 'rust-baseline' && 180 || 45 }}"],
            'the merge Rust suite requires the same 180-minute budget; other merge lanes retain 45 minutes')
    require("    if: github.event_name == 'pull_request'\n" in merge, 'merge lane event boundary')
    require('      fail-fast: false\n' in merge, 'all merge lanes retain their outcomes')
    lanes = re.search(r'^        lane: \[([^\]]+)\]$', merge, re.M)
    require(lanes is not None and {p.strip() for p in lanes[1].split(',')} == set(required) - {'rust-baseline'},
            'prospective merge retains four lanes; required Rust uses its separate fail-closed fan-in')
    for line in ['TRNM_EXPECTED_SOURCE_SHA: ${{ github.sha }}',
                 'TRNM_EXPECTED_CANDIDATE_SHA: ${{ github.event.pull_request.head.sha }}',
                 'TRNM_EXPECTED_BASE_SHA: ${{ github.event.pull_request.base.sha }}']:
        require('      ' + line + '\n' in merge, 'merge event identity binding')
    command = ('verify_ci_source.py --kind prospective-merge --expected-head "$TRNM_EXPECTED_CANDIDATE_SHA" '
               '--expected-base "$TRNM_EXPECTED_BASE_SHA" --expected-merge "$TRNM_EXPECTED_SOURCE_SHA"')
    require(merge.count(command) == 2, 'merge parents and source checked before and after execution')
    require('        run: bash scripts/ci/ci_job.sh "${{ matrix.lane }}"\n' in merge,
            'merge uses actual lane execution, not only a source checker')
    # Both required names remain real jobs, even when a dependency failed or
    # was cancelled/skipped. A receipt cannot replace the aggregate job result.
    for kind, worker, fanin in [('head', 'rust-baseline-shards', 'rust-baseline'),
                                ('prospective-merge', 'prospective-rust-shards', 'prospective-rust-baseline')]:
        work, gate = jobs[worker], jobs[fanin]
        for block in (work, gate):
            require(re.findall(r'^    timeout-minutes: (.+)$', block, re.M) == ['180'],
                    'each Rust shard and fan-in retains its original 180-minute budget')
        event = "github.event_name == 'pull_request'"
        conditions = re.findall(r'^    if: (.+)$', work, re.M)
        require(conditions == ([event] if kind == 'prospective-merge' else []), 'Rust shard event boundary')
        condition = "${{ always() && " + event + " }}" if kind == 'prospective-merge' else 'always()'
        require(re.findall(r'^    if: (.+)$', gate, re.M) == [condition] and
                re.findall(r'^    needs: (.+)$', gate, re.M) == [worker], 'Rust fan-in must run after all outcomes')
        require(re.findall(r'^    name: (.+)$', gate, re.M) ==
                ['prospective-merge (rust-baseline)' if kind == 'prospective-merge' else 'rust-baseline'],
                'original required Rust check name')
        require('      fail-fast: false\n      matrix:\n        shard: [runtime, quality]\n' in work and
                '    strategy:' not in gate, 'both required Rust shards execute without fail-fast')
        args = '--kind head --candidate "$TRNM_EXPECTED_SOURCE_SHA" --tested "$TRNM_EXPECTED_SOURCE_SHA"'
        if kind == 'prospective-merge':
            args = '--kind prospective-merge --candidate "$TRNM_EXPECTED_CANDIDATE_SHA" --base "$TRNM_EXPECTED_BASE_SHA" --tested "$TRNM_EXPECTED_SOURCE_SHA"'
            for block in (work, gate):
                for line in ['TRNM_EXPECTED_SOURCE_SHA: ${{ github.sha }}',
                             'TRNM_EXPECTED_CANDIDATE_SHA: ${{ github.event.pull_request.head.sha }}',
                             'TRNM_EXPECTED_BASE_SHA: ${{ github.event.pull_request.base.sha }}']:
                    require('      ' + line + '\n' in block, 'Rust shard merge identity')
                require(block.count(command) == 2, 'Rust merge checked before and after')
        run = 'python3 scripts/ci/rust_baseline_shards.py run ' + args + ' --shard "${{ matrix.shard }}" --output "$RUNNER_TEMP/ci-observations/rust-shard.json"'
        check = 'python3 scripts/ci/rust_baseline_shards.py check ' + args + ' --inputs "$RUNNER_TEMP/rust-shards" --dependency-result "$TRNM_RUST_SHARD_RESULT" --output "$RUNNER_TEMP/ci-observations/rust-fanin.json"'
        require('      - name: Run retained Rust shard\n        run: ' + run + '\n' in work and
                work.count('rust_baseline_shards.py ') == 1, 'real retained Rust shard execution')
        require('      - name: Require both successful exact-source Rust shards\n        if: always()\n        run: ' + check + '\n' in gate and
                gate.count('rust_baseline_shards.py ') == 1 and
                '      TRNM_RUST_SHARD_RESULT: ${{ needs.' + worker + '.result }}\n' in gate,
                'Rust fan-in must require dependency success and exact receipts after failure')
        artifact = 'rust-shard-' + kind + '-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}'
        require('          name: rust-observations-' + kind + '-${{ env.TRNM_EXPECTED_SOURCE_SHA }}-${{ github.run_attempt }}-${{ matrix.shard }}\n' in work and
                '          path: ${{ runner.temp }}/ci-observations/\n' in work and
                '          path: |\n            ${{ runner.temp }}/ci-observations/rust-shard.json\n            ${{ runner.temp }}/ci-observations/rust-shard.sh\n' in work,
                'full native evidence retained separately from lightweight fan-in proof')
        require('          name: ' + artifact + '-${{ matrix.shard }}\n' in work and
                '          pattern: ' + artifact + '-*\n' in gate and
                'uses: ' + DOWNLOAD in gate and '          path: ${{ runner.temp }}/rust-shards/\n' in gate and
                '          merge-multiple: false\n' in gate, 'distinct current-source current-attempt shard artifacts')
    script = (root / 'scripts/ci/ci_job.sh').read_text()
    check_independent_conformance(script, set(required))
    require('    python3 scripts/ci/run_fuzz_smoke.py\n' in script,
            'instrumented fuzz execution missing')
    require(all(SIGNED_STATE_PYTHON in jobs[name] for name in
                ('rust-baseline-shards', 'prospective-rust-shards')) and
            "if: matrix.lane == 'protocol-contract' || matrix.lane == 'external-evidence-contract' || matrix.lane == 'rust-baseline'" in merge,
            'both Rust lanes require the pinned isolated signed-state oracle dependencies')
    require('    python3 scripts/ci/run_supply_chain.py\n' in script,
            'locked dependency checks missing')
    require('    python3 scripts/ci/test_cross_arch_cost.py\n' in script,
            'cross-architecture evidence negative checks missing')
    lane_pairs = re.findall(r'(?ms)^  ([a-z][a-z0-9-]*)\)\n(.*?)(?=^    ;;$)', script)
    zero_negative = '    python3 scripts/ci/test_zero_locality_cost.py\n'
    require(zero_negative in dict(lane_pairs)['repository-truth'] and script.count(zero_negative) == 1,
            'zero locality evidence negative checks must execute in repository-truth')
    one_zero_negative = '    python3 scripts/ci/test_one_zero_locality_cost.py\n'
    require(one_zero_negative in dict(lane_pairs)['repository-truth'] and script.count(one_zero_negative) == 1,
            'one-zero locality evidence negative checks must execute in repository-truth')
    maintenance_negative = '    python3 scripts/ci/test_maintenance_cost.py\n'
    require(maintenance_negative in dict(lane_pairs)['repository-truth'] and
            script.count(maintenance_negative) == 1,
            'fixed maintenance evidence negative checks must execute once in repository-truth')
    rejection_negative = '    python3 scripts/ci/test_work_rejection_report.py\n'
    require(rejection_negative in dict(lane_pairs)['repository-truth'] and
            script.count(rejection_negative) == 1,
            'actual rejection cost evidence negatives must execute once in repository-truth')
    archive_negative = '    python3 scripts/ci/test_account_archive_conformance.py\n'
    require(archive_negative in dict(lane_pairs)['repository-truth'] and script.count(archive_negative) == 1,
            'archive native/oracle receipt negatives must execute once in repository-truth')
    execution_negative = '    python3 scripts/ci/test_run_account_execution_conformance.py\n'
    require(execution_negative in dict(lane_pairs)['repository-truth'] and script.count(execution_negative) == 1,
            'account execution receipt negatives must execute once in repository-truth')
    require('    python3 scripts/run_public_v3_service_campaign.py --out ' in script,
            'source-bound mixed-service campaign and retained refusal checks missing')
    require(jobs['fuzz-smoke'].count('run: bash scripts/ci/install_ci_tools.sh fuzz') == 1 and
            merge.count('run: bash scripts/ci/install_ci_tools.sh fuzz') == 1, 'pinned fuzz installation missing')
    require(all(jobs[name].count('run: bash scripts/ci/install_ci_tools.sh supply-chain') == 1 for name in
                ('rust-baseline-shards', 'prospective-rust-shards')) and
            merge.count('run: bash scripts/ci/install_ci_tools.sh supply-chain') == 1,
            'pinned dependency auditor installation missing')
    versions = dict(line.split('=', 1) for line in (root / 'scripts/ci/tool-versions.env').read_text().splitlines()
                    if line and not line.startswith('#'))
    require(set(versions) == {'TRNM_CARGO_FUZZ_VERSION', 'TRNM_FUZZ_TOOLCHAIN', 'TRNM_CARGO_DENY_VERSION'},
            'explicit tool inventory')
    require(all(re.fullmatch(r'\d+\.\d+\.\d+', versions[key]) for key in
                ('TRNM_CARGO_FUZZ_VERSION', 'TRNM_CARGO_DENY_VERSION')) and
            re.fullmatch(r'nightly-\d{4}-\d{2}-\d{2}', versions['TRNM_FUZZ_TOOLCHAIN']) is not None,
            'floating toolchain/tool version')
    require((root / 'tests/fuzz/Cargo.lock').is_file(), 'isolated fuzz lockfile missing')
    normal = tomllib.loads((root / 'trillionnium/Cargo.lock').read_text())['package']
    fuzz = tomllib.loads((root / 'tests/fuzz/Cargo.lock').read_text())['package']
    resolved = {}
    for package in normal:
        resolved.setdefault((package['name'], package.get('source')), set()).add(package['version'])
    for package in fuzz:
        key = (package['name'], package.get('source'))
        require(key not in resolved or package['version'] in resolved[key],
                'fuzz must instrument the same shared dependency versions as the native lockfile: ' + package['name'])
    # A lock may preserve every version yet omit a newly required dependency
    # edge of a local crate. Check unconditional nonoptional normal dependencies;
    # dev/target/optional edges remain Cargo's responsibility, not inferred here.
    workspace = tomllib.loads((root / 'trillionnium/Cargo.toml').read_text())
    inherited = workspace.get('workspace', {}).get('dependencies', {})
    local = {}
    for member in workspace['workspace']['members']:
        manifest = tomllib.loads((root / 'trillionnium' / member / 'Cargo.toml').read_text())
        local[manifest['package']['name']] = manifest
    for package in fuzz:
        if package.get('source') is not None or package['name'] not in local:
            continue
        edges = {edge.split(' ', 1)[0] for edge in package.get('dependencies', [])}
        for alias, specification in local[package['name']].get('dependencies', {}).items():
            detail = specification if isinstance(specification, dict) else {}
            if detail.get('optional', False):
                continue
            parent_detail = inherited.get(alias, {}) if detail.get('workspace', False) else {}
            parent_detail = parent_detail if isinstance(parent_detail, dict) else {}
            dependency = detail.get('package', parent_detail.get('package', alias))
            require(dependency in edges,
                    'fuzz lock missing required local dependency edge: '
                    + package['name'] + ' -> ' + dependency)
    return {'head_jobs': len(required), 'merge_lanes': len(required),
            'native_cost_architectures': 2, 'artifact_comparison_jobs': 1,
            'w1_actual_reuse_v3_cells': 4, 'inline_source_pins': inline_source_pins,
            'tests_executed': False}


if __name__ == '__main__':
    print(json.dumps(validate(), sort_keys=True))
