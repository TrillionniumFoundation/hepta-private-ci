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
- Product caller state: `source_composed_runtime_fleet_bao_browser_and_agentd_automation_hosts_not_product_activated`
- Production writer state: `authority_owner_source_implemented_not_activated`

## Operations

| Operation | State | Source | Tests |
| --- | --- | --- | ---: |
| `finaluseauthority` | `source_implemented_named_agentd_automation_host_not_product_activated` | `codex-rs/hepta-contracts/src/final_use.rs` | 5 |
| `store` | `source_implemented_not_product_activated` | `codex-rs/hepta-contracts/src/final_use_store.rs` | 1 |
| `authority_lease_registry` | `source_implemented_exact_predecessor_and_lock_time_regressions_not_product_activated` | `codex-rs/hepta-contracts/src/authority_lease.rs` | 1 |
| `final_use_approval_verifier` | `source_implemented_registered_host_not_product_activated` | `codex-rs/hepta-contracts/src/final_use_control.rs` | 1 |
| `final_use_revocation_feed_verifier` | `source_implemented_agentd_refresh_and_pending_admission_fence_not_product_activated` | `codex-rs/hepta-contracts/src/final_use_control.rs` | 3 |
| `authority_external_trust` | `source_interface_and_named_agentd_backend_implemented_target_qualification_external` | `codex-rs/hepta-contracts/src/authority_trust.rs` | 3 |
| `final_use_revocation_convergence` | `source_implemented_transport_external` | `codex-rs/hepta-contracts/src/final_use_control.rs` | 1 |
| `verified_use_witness_v1` | `source_implemented_non_authorizing_evidence_durably_consumed_by_taskflow_not_activated` | `codex-rs/hepta-contracts/src/verified_use_witness.rs` | 4 |
| `verified_use_token_witness_v1` | `source_implemented_non_authorizing_evidence_durably_consumed_by_taskflow_not_activated` | `codex-rs/hepta-contracts/src/verified_use_witness.rs` | 3 |

## Repository-controlled gaps

- Retain current exact-head and deterministic synthetic-merge execution receipts after the hardened authority changes.
- Keep B4 and CALLERS.toml bound to the observed closed caller set as product integrations change.
- Compose remaining target-only ModulePorts only at their real owner boundaries with one canonical authority reference and revision.
- Do not promote the named Agentd trust backend into an attestation or rollback-independent deployment claim without target-host evidence.

## External evidence gates

- deployed fleet revocation wire fanout and measured convergence/freshness latency qualification
- selected-host rollback-independent storage/backup-domain qualification for the Agentd or other AuthorityFrontierStore backend
- attested or otherwise independently protected AuthorityClock qualification and clock-uncertainty receipt
- HSM/KMS key custody, staged rotation and compromise-response ceremony
- complete schema-v2 target-host capacity and crash/fault evidence
- independent semantic review
- operator acceptance, canary, promotion and release
