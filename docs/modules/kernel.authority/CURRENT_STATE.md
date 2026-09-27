# kernel.authority current state

This file is generated from `IMPLEMENTATION_MAP.json` by
`scripts/kernel_authority_status.py`. It records source-navigation and
readiness facts only; it grants no deployment, activation or release authority.

## Claims

- Production implementation: `false`
- Product execution proved: `false`
- Independent acceptance: `false`
- Activation: `false`
- Release: `false`
- Product caller state: `fleet-browser-agentd-and-bao-source-composed-candidate-pilots-defined-not-product-activated`
- Production writer state: `authority-owner-and-agentd-effect-owner-source-implemented-not-activated`

## Operations

| Operation | State | Source | Tests |
| --- | --- | --- | ---: |
| `authority_lease_registry` | `source_implemented_owner_cas_retired_lineage_epoch_and_rollback_fencing_not_product_activated` | `codex-rs/hepta-contracts/src/authority_lease.rs` | 2 |
| `authority_dispatch_binding` | `source_implemented_one_shot_lock_scoped_final_dispatch_with_closed_product_callers` | `codex-rs/hepta-contracts/src/authority_trust.rs` | 3 |
| `final_use_authority` | `source_implemented_nonce_claim_final_entry_durable_pending_revocation_v4_and_key_ring_recovery_not_product_activated` | `codex-rs/hepta-contracts/src/final_use.rs` | 4 |
| `final_use_control` | `source_implemented_independent_approval_signed_feed_and_receipt_bound_convergence_transport_external` | `codex-rs/hepta-contracts/src/final_use_control.rs` | 2 |
| `production_trust_bundle` | `source_implemented_mandatory_clock_frontier_kms_custody_and_external_receipts_target_qualification_external` | `codex-rs/hepta-contracts/src/authority_trust.rs` | 2 |
| `verified_use_witness` | `source_implemented_non_authorizing_entry_evidence_durably_consumed_by_taskflow_not_activated` | `codex-rs/hepta-contracts/src/verified_use_witness.rs` | 3 |
| `agentd_external_trust_host` | `named_host_source_implemented_monotonic_floor_external_frontier_private_state_and_rollback_detection_not_attested` | `codex-rs/hepta-agentd/src/authority_trust_host.rs` | 1 |
| `agentd_effect_owner` | `source_implemented_exact_wire_dispatch_durable_attempt_witness_terminal_receipt_and_reconciliation_not_activated` | `codex-rs/hepta-agentd/src/automation_effect_host.rs` | 2 |
| `candidate_product_pilot` | `candidate_bound_fleet_browser_agentd_restart_revoke_rollback_rotation_and_pending_crash_matrix_process_pilot_defined_execution_pending` | `qualification/kernel-authority/runtime_qualification.py` | 6 |
| `performance_qualification` | `qualification_measurement_defined_for_put_dispatch_revoke_contention_throughput_snapshot_and_reopen_no_production_slo` | `codex-rs/hepta-contracts/tests/kernel_authority_benchmark.rs` | 1 |
| `storage_scaling_model` | `executable_reference_model_for_wal_checkpoint_corruption_recovery_sharding_and_capacity_not_runtime` | `qualification/kernel-authority/storage_model.py` | 1 |

## Repository-controlled gaps

- Obtain green required exact-head and deterministic synthetic-merge receipts for the current candidate SHA.
- Keep the canonical B4 and extension API inventories exhaustive as authority APIs and product callers change.
- Retain candidate identity, command, log digest and result in every product-pilot and performance receipt.
- Keep production constructors mandatory and fail closed; compatibility clocks, local frontiers or evidence-only key claims must not satisfy them.
- Do not replace the current authority spine with the WAL/checkpoint reference model without preserving linearization and anti-rollback proofs.

## External evidence gates

- independently protected or attested time source and measured maximum uncertainty
- rollback-independent linearizable frontier backend plus snapshot and disaster-recovery drill
- KMS or HSM custody for issuer, approval and revocation roles with staged rotation and compromise-response receipts
- deployed revocation fanout under normal delay partition restart and recovery scenarios
- target-host filesystem mount backup identity and boot rollback-detection qualification
- target-host p50 p95 p99 throughput lock-wait fsync snapshot and restart measurements with approved SLOs
- verifier-only topology evidence and independent semantic review
- operator acceptance canary promotion and release
