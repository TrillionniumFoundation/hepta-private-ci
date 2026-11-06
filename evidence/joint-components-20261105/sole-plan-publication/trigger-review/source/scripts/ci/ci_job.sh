#!/usr/bin/env bash
set -euo pipefail
export RUST_TEST_THREADS="${RUST_TEST_THREADS:-1}"
case "${1:?required job}" in
  repository-truth)
    bash scripts/project-preflight.sh --audit
    python3 scripts/ci/test_project_boundary.py
    # A passing HOLD check does not certify whole-chain PQ or PQ-128.
    python3 scripts/ci/test_pq_chain_claim_guard.py
    python3 -m unittest discover -s scripts/ci -p 'test_pq_authority_surface_scan.py' -v
    python3 scripts/ci/pq_authority_surface_scan.py --summary-only
    python3 -m unittest discover -s scripts/ci -p 'test_pq_external_rollback_oracle.py' -v
    python3 -m unittest discover -s scripts/ci -p 'test_pq_quantum_daa_scenarios.py' -v
    # Public-input framing only: no seed proof or signature qualification.
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_pq_seed_recovery_v1.py' -v

    # Conditional resource/event models retain unknown W1 hardware and protocol gates.
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_quantum_oracle_resources.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_quantum_network_sim.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_quantum_candidate_check_clock.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_quantum_adversarial_search.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_quantum_resource_clock.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_w1_quantum_oracle.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_w1_marked_domain.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_w1_quantum_restricted_oracle.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_fast_daa_reference_component.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_parallel_variable_ohie.py' -v
    # Finite ordering and report consistency do not qualify a successor protocol.
    python3 -m unittest discover -s formal/pon-nakamoto-v1 -p 'test_ghostdag_order_reference.py' -v
    python3 -m unittest discover -s formal/pon-nakamoto-v1/experiments -p 'test_architecture_compare.py' -v
    python3 scripts/ci/pq_chain_claim_guard.py
    python3 scripts/ci/check_repository.py
    python3 scripts/refresh_distributed_source_inventory.py --check
    python3 scripts/ci/test_repository.py
    python3 scripts/ci/test_invariants_registry.py
    python3 scripts/ci/test_responsibility_evidence.py
    python3 scripts/ci/test_applicability.py
    python3 scripts/ci/test_ci_contract.py
    python3 scripts/ci/test_ci_execution.py
    python3 -B scripts/ci/test_llm_hosted_once.py
    python3 scripts/test_llm_runtime_release.py
    python3 scripts/ci/test_replay_pinned_native.py
    python3 scripts/ci/test_cross_arch_cost.py
    python3 scripts/ci/test_zero_locality_cost.py
    python3 scripts/ci/test_zero_paired_cost.py
    python3 scripts/ci/test_one_zero_locality_cost.py
    python3 scripts/ci/test_maintenance_cost.py
    python3 scripts/ci/test_work_rejection_report.py
    # These in-memory counterexamples use unchanged retained inputs, not a new hardware observation.
    python3 scripts/ci/test_pon_w1_budget_readers.py --raw-dir evidence/pon-upgrade-implementation-20261018/native-rounds/chain-p0-native-54
    python3 scripts/ci/test_pon_public_v3_phase_read.py
    python3 scripts/ci/test_pon_public_v3_policy_read.py
    python3 scripts/ci/test_pon_v3_cookie_cpu_study.py
    python3 scripts/ci/test_run_pon_w1_native_campaign.py
    python3 scripts/ci/test_pon_w1_cost_matrix_reader.py
    python3 scripts/ci/test_pon_w1_reused_cost_reader_v3.py
    python3 scripts/ci/test_run_w1_reused_cost_v3.py
    python3 scripts/ci/test_llm_cell_handoff_deadline.py
    python3 scripts/ci/test_read_original_native_campaign.py \
      --artifact-dir evidence/pon-upgrade-implementation-20261018/native-rounds/chain-pr327-original-campaign-39694587963 \
      --expected-manifest-sha256 12406cc156e57c130fa14af2b50b386031ec3640ce7f0234ed5bc9f0a700aac3 \
      --expected-head 9e705ccf75b7318dcc4bda4815956f58beb10e72 \
      --expected-tree 521ae87a28060d545979069b189eebbc74a71fd8 --retained-subset
    python3 scripts/ci/test_account_archive_conformance.py
    python3 scripts/ci/test_run_account_execution_conformance.py
    python3 scripts/ci/report_current_implementation.py --check
    python3 scripts/ci/test_work_cost_report.py
    python3 scripts/test_qualification_runtime.py
    ;;
  protocol-contract)
    python3 scripts/ci/run_from_zero_host.py -- python3 scripts/ci/run_from_zero_native.py --out "${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}/from-zero-native"
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
    # Complete source-router relation controls are research checks, not native/work-security qualification.
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
    ;;
  fuzz-smoke)
    python3 scripts/ci/test_repository.py
    python3 formal/pon-nakamoto-v1/test_reference.py
    python3 formal/pon-nakamoto-v1/test_honest_rate_model.py -v
    cargo test --locked --manifest-path trillionnium/Cargo.toml -p trnm-crypto-primitives fixed_hash_text -- --nocapture
    python3 scripts/ci/run_fuzz_smoke.py
    ;;
  rust-baseline)
    cargo fmt --manifest-path trillionnium/Cargo.toml --all -- --check
    python3 scripts/ci/run_supply_chain.py
    # The full workspace matrix includes both evaluation_sync_observation tests.
    # Run that target once in this matrix; a separate pre-run duplicated over ten
    # minutes of actual sync work and left the hosted 45-minute job incomplete.
    (
      trnm_model_receipt_root="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}"
      mkdir -p "$trnm_model_receipt_root"
      export TRNM_MODEL_COMPOSITION_VECTORS="$trnm_model_receipt_root/model-composition"
      test ! -e "$TRNM_MODEL_COMPOSITION_VECTORS"
      test ! -L "$TRNM_MODEL_COMPOSITION_VECTORS"
      mkdir "$TRNM_MODEL_COMPOSITION_VECTORS"
      export TRNM_MODEL_COMPOSITION_RUN_ID="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
      test -n "$TRNM_MODEL_COMPOSITION_RUN_ID"
      printf 'model-composition directory=%s run_id=%s\n' "$TRNM_MODEL_COMPOSITION_VECTORS" "$TRNM_MODEL_COMPOSITION_RUN_ID"
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
    (
      trnm_native_receipt_root="${TRNM_CI_RECEIPT_DIR:-${RUNNER_TEMP:-/tmp}/trnm-ci-$$}"
      mkdir -p "$trnm_native_receipt_root"
      test ! -e "$trnm_native_receipt_root/native-capacity-release.log"
      test ! -L "$trnm_native_receipt_root/native-capacity-release.log"
      cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-capacity-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-capacity-release.log" --test account_archive_prototype::native_store::batch_tests::native_authenticated_full_capacity_refund_entry_and_pending_reorganization_recover
      test ! -e "$trnm_native_receipt_root/native-growth-reference-release.log"
      test ! -L "$trnm_native_receipt_root/native-growth-reference-release.log"
      test ! -e "$trnm_native_receipt_root/native-growth-reference"
      test ! -L "$trnm_native_receipt_root/native-growth-reference"
      TRNM_NATIVE_GROWTH_EXPORT_DIRECTORY="$trnm_native_receipt_root/native-growth-reference" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-growth-reference-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-growth-reference-release.log" --test store::growth_reference::tests::native_growth_reference_65537_signed_accounts_and_cold_reopen
      test ! -e "$trnm_native_receipt_root/native-growth-reference/readback.json"
      test ! -L "$trnm_native_receipt_root/native-growth-reference/readback.json"
      python3 -B formal/pon-nakamoto-v1/check_gsc2_native_readback.py --artifact-dir "$trnm_native_receipt_root/native-growth-reference" --source-root "$(pwd -P)" --minimum-accounts 65537 > "$trnm_native_receipt_root/native-growth-reference/readback.json"
      test ! -e "$trnm_native_receipt_root/native-growth-v2-release.log"
      test ! -L "$trnm_native_receipt_root/native-growth-v2-release.log"
      test ! -e "$trnm_native_receipt_root/native-growth-v2"
      test ! -L "$trnm_native_receipt_root/native-growth-v2"
      TRNM_NATIVE_GROWTH_V2_EXPORT_DIR="$trnm_native_receipt_root/native-growth-v2" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-growth-v2-release.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-growth-v2-release.log" --test store::growth::tests::native_growth_v2_signed_cross_65536_bounded_io_zero_nonce_and_reopen
      test -s "$trnm_native_receipt_root/native-growth-v2/native.json"
      test ! -L "$trnm_native_receipt_root/native-growth-v2/native.json"
      test ! -e "$trnm_native_receipt_root/native-account-verification-cost"
      test ! -L "$trnm_native_receipt_root/native-account-verification-cost"
      test ! -e "$trnm_native_receipt_root/native-account-verification-cost.log"
      test ! -L "$trnm_native_receipt_root/native-account-verification-cost.log"
      TRNM_NATIVE_ACCOUNT_VERIFY_COST_DIRECTORY="$trnm_native_receipt_root/native-account-verification-cost" cargo test --offline --locked --release --manifest-path trillionnium/Cargo.toml -p trnm-pon-node --lib account_archive_prototype::native_primitive_tests::native_complete_account_verification_cost -- --exact --ignored --nocapture --test-threads=1 2>&1 | tee "$trnm_native_receipt_root/native-account-verification-cost.log"
      python3 scripts/ci/check_required_native_test.py "$trnm_native_receipt_root/native-account-verification-cost.log" --test account_archive_prototype::native_primitive_tests::native_complete_account_verification_cost
    )
    cargo test --locked --manifest-path trillionnium/Cargo.toml --workspace --doc --all-features
    cargo clippy --locked --manifest-path trillionnium/Cargo.toml --workspace --all-targets --all-features -- -D warnings
    ;;
  external-evidence-contract)
    python3 scripts/ci/prepare_evidence_sources.py
    python3 scripts/ci/test_evidence_sources.py
    python3 scripts/ci/check_repository.py
    python3 scripts/ci/test_repository.py EvidenceBoundaryTests
    python3 scripts/ci/check_pon_evidence.py
    python3 scripts/ci/test_pon_evidence.py
    python3 scripts/ci/check_invariant_evidence.py --historical
    python3 scripts/ci/test_invariant_evidence.py
    python3 scripts/ci/check_completion_evidence.py --historical
    python3 scripts/ci/test_completion_evidence.py
    python3 scripts/ci/check_evaluation_bundle_evidence.py --historical
    python3 scripts/ci/check_client_confirmation_evidence.py --historical
    python3 scripts/ci/check_client_confirmation_evidence.py --historical --evidence evidence/pon-native-session-v1
    python3 scripts/ci/check_client_confirmation_evidence.py --historical --evidence evidence/pon-native-node-v1
    python3 scripts/ci/check_client_confirmation_evidence.py --historical --evidence evidence/pon-closed-round-v1
    python3 scripts/ci/check_public_readiness_evidence.py --historical --evidence evidence/pon-public-readiness-v1
    python3 scripts/ci/test_public_readiness_evidence.py
    python3 scripts/ci/check_native_node_supplements.py --historical
    python3 scripts/ci/test_native_node_supplements.py
    python3 scripts/ci/test_native_session_evidence.py
    python3 scripts/ci/test_client_confirmation_evidence.py
    python3 scripts/ci/test_evaluation_bundle_evidence.py
    python3 scripts/ci/report_module_evidence.py --format markdown
    python3 scripts/pon_work_cost_report.py --verify evidence/pon-contract-authority-v1/work-cost --historical
    python3 scripts/pon_work_cost_report.py --verify evidence/pon-native-session-v1/work-cost --historical
    python3 scripts/pon_work_cost_report.py --verify evidence/pon-native-node-v1/work-cost --historical
    python3 scripts/pon_work_cost_report.py --verify evidence/pon-closed-round-v1/work-cost --historical
    python3 scripts/ci/check_four_priority_evidence.py
    python3 scripts/ci/test_four_priority_evidence.py
    python3 scripts/pon_work_cost_report.py --verify evidence/pon-four-priority-audit-v1/work-cost --historical
    ;;
  *) printf '%s\n' 'unknown CI job' >&2; exit 2 ;;
esac
