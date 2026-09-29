# cognitive.store current status

Generated from `CURRENT_STATE.json`; do not hand-edit.

Source presence is not execution, target-host qualification, or acceptance.

| Gate | State |
|---|---|
| `sourceChangesPresent` | `true` |
| `productionImplementation` | `false` |
| `productExecutionProved` | `false` |
| `targetHostQualified` | `false` |
| `independentAcceptance` | `false` |
| `activation` | `false` |
| `release` | `false` |

## Invariant traceability

| Invariant | Source | Regression / measurement | Evidence scope |
|---|---|---|---|
| `CS-REC-001` — Recovery dispositions survive the Agentd boundary | `codex-rs/hepta-agentd/src/error.rs`<br>`codex-rs/hepta-agentd/src/production_writer_host.rs` | `codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::all_recovery_dispositions_preserve_type_and_error_source` | Typed conversion and real product ingress; target host pending |
| `CS-WIT-001` — A stale witness cannot admit a post-commit restart | `codex-rs/hepta-memory/src/cognitive_store_recovery.rs` | `codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::committed_child_exit_before_witness_update_rejects_stale_restart` | Real child exit / SQLite; fixture authority only |
| `CS-PUB-001` — A possibly published or unresolvable candidate is retained as indeterminate | `codex-rs/hepta-memory/src/cognitive_store_recovery.rs`<br>`codex-rs/hepta-memory/tests/cognitive_recovery_publication_fault.rs` | `codex-rs/hepta-memory/tests/cognitive_recovery_publication_fault.rs::post_rename_directory_fsync_failure_is_indeterminate_and_retains_candidate`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs::post_rename_publication_failure_is_indeterminate_and_retains_candidate`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery.rs::unreadable_active_pointer_retains_candidate_as_indeterminate` | Real Linux directory-fsync injection through the public recovery entry; selected-host filesystem qualification pending |
| `CS-AUTH-001` — Revocation prevents later writes without rewriting committed history | `codex-rs/hepta-agentd/src/cognitive_bootstrap.rs`<br>`codex-rs/hepta-memory/src/production_writer.rs` | `codex-rs/hepta-agentd/tests/cognitive_bootstrap.rs::signed_bootstrap_rotates_restarts_canaries_and_revokes_live`<br>`codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::revocation_after_commit_preserves_cut_and_rejects_next_mutation` | Signed and live-verifier fixtures; independently administered signer pending |
| `CS-ROLL-001` — Re-admission uses a fresh grant-bound writer generation | `codex-rs/hepta-cognitive-store/src/bootstrap.rs` | `codex-rs/hepta-agentd/tests/cognitive_bootstrap.rs::signed_bootstrap_rotates_restarts_canaries_and_revokes_live`<br>`codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::fresh_generation_reopens_reconciled_cut_without_replaying_memory` | Repository restart/rotation; selected-host rollback pending |
| `CS-LIFE-001` — History and tombstones survive reopen without treating deletion as erasure | `codex-rs/hepta-memory/examples/cognitive_store_history_perf.rs` | `codex-rs/hepta-memory/examples/cognitive_store_history_perf.rs` | Measured owner history; pruning and physical erasure not claimed |
| `CS-EVID-001` — Current source and all required execution records are independently checked | `scripts/cognitive_store_map_verify.py`<br>`scripts/cognitive_qualification_manifest.py` | `scripts/test_cognitive_store_map.py`<br>`scripts/test_cognitive_qualification_manifest.py` | Exact source objects, no inherited success |
| `CS-SRC-001` — Signed bootstrap source identity matches the trusted deployment before recovery | `codex-rs/hepta-agentd/src/cognitive_bootstrap.rs` | `codex-rs/hepta-agentd/tests/cognitive_bootstrap.rs` | Direct source identity check; deployment attestation remains external |
| `CS-REC-002` — Authority is rechecked before recovery pointer publication | `codex-rs/hepta-memory/src/cognitive_store_recovery.rs` | `codex-rs/hepta-memory/src/cognitive_store_recovery_final_use_tests.rs` | Real SQLite final-use revocation and unchanged predecessor; native execution pending |
| `CS-READ-001` — Normal host read pages preserve exact cut without a mutable escape | `codex-rs/hepta-cognitive-store/src/durable.rs`<br>`codex-rs/hepta-agentd/src/production_writer_host.rs` | `codex-rs/hepta-agentd/tests/cognitive_store_read_pages.rs`<br>`codex-rs/hepta-agentd/tests/cognitive_store_host_read_pages.rs` | Actual host API and normal features; fixture authority, not deployment evidence |
| `CS-API-001` — API denials require successful positive compilation controls | `scripts/cognitive_store_api_probe.py` | `scripts/test_cognitive_store_api_probe.py` | Default, host-unified and qualification visibility; not runtime authorization or OS isolation |
| `CS-FILE-002` — A current-cut witness leaves the exact SQLite owner image and existing sidecars private and identity-stable for descriptor recovery | `codex-rs/hepta-memory/src/cognitive_store.rs`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery.rs` | `codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs::current_cut_capture_hardens_existing_sqlite_sidecars_without_replacing_them` | Owner-controlled DB/WAL/SHM/journal identity; selected-host filesystem qualification pending |
| `CS-PERF-001` — Release recovery reports wait, held time and sampled resource growth separately | `codex-rs/hepta-memory/examples/cognitive_store_recovery_perf.rs`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery.rs` | `codex-rs/hepta-memory/examples/cognitive_store_recovery_perf.rs`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery_final_use_tests.rs` | Three recoveries per profile; sampled lower bounds and fixture-verifier cost, not host SLO acceptance |
| `CS-OPS-001` — Expired grants do not prevent recording authenticated terminal evidence | `tools/cognitive-store-host-bootstrap/bootstrap.py` | `tools/cognitive-store-host-bootstrap/test_expired_cli.py` | Operational records only; expired admission and reactivation remain denied |
| `CS-LIFE-002` — Every declared storage owner signs its exact lifecycle obligation | `tools/cognitive-store-host-bootstrap/lifecycle.py` | `tools/cognitive-store-host-bootstrap/test_lifecycle.py` | Real Ed25519 verification with fixture keys; owner attestations are not independently observed physical erasure |
| `CS-ARCH-001` — Encrypted cold archives preserve the exact owner cut and never authorize pruning or activation | `tools/cognitive-store-host-bootstrap/archive.py`<br>`codex-rs/hepta-memory/src/cognitive_store_recovery_read_only.rs`<br>`codex-rs/hepta-memory/src/bin/cognitive-store-archive-check.rs` | `tools/cognitive-store-host-bootstrap/test_archive.py`<br>`codex-rs/hepta-memory/tests/cognitive_archive_owner.rs::signed_archive_restores_real_correction_and_tombstone_history` | Bounded encrypted full-history cold-generation transfer; native execution and independently managed archive/restore acceptance remain separate; hot pruning and physical erasure not claimed |
| `CS-ARCH-002` — Lost archive or restore responses are observed without replay or adoption | `tools/cognitive-store-host-bootstrap/archive.py`<br>`tools/cognitive-store-host-bootstrap/archive_observation.py` | `tools/cognitive-store-host-bootstrap/test_publication_observation.py`<br>`tools/cognitive-store-host-bootstrap/test_archive.py` | Current independently signed observation authority; original operation may be expired; readable bytes do not prove past publication durability |
| `CS-FILE-001` — Signed input reads are nonblocking and bound to the current pathname | `tools/cognitive-store-host-bootstrap/lifecycle.py` | `tools/cognitive-store-host-bootstrap/test_publication_observation.py` | Real POSIX FIFO, replacement, link, mode and byte-limit regressions; not a deployment isolation claim |
| `CS-PLAN-001` — Only the committed command, workload and test threshold can satisfy qualification | `scripts/cognitive_store_plan.py`<br>`scripts/cognitive_store_qualify.py`<br>`scripts/cognitive_qualification_manifest.py`<br>`scripts/hepta_ci_exec.py` | `scripts/test_cognitive_plan_binding.py`<br>`scripts/test_cognitive_qualification_manifest.py`<br>`scripts/test_hepta_ci_exec.py`<br>`scripts/test_hepta_ci_exec_deadline.py`<br>`scripts/test_hepta_ci_exec_output.py` | Real command runner in disposable Git repositories; exact production candidate and native matrix remain separately required |
| `CS-OBS-002` — Publication observation pins scratch identity and rechecks the created image at final use | `tools/cognitive-store-host-bootstrap/archive_observation.py`<br>`tools/cognitive-store-host-bootstrap/archive_publication.py` | `tools/cognitive-store-host-bootstrap/test_observation_boundary.py`<br>`tools/cognitive-store-host-bootstrap/test_publication_observation.py` | Real encrypted codec and filesystem; native checker mocked in protocol tests; no replay, hot pruning or erasure authority |

## Remaining external evidence

- Independent signer governance and retained current-cut witness outside the rollback domain.
- Trusted reconciliation of a commit-to-witness publication gap, without deriving authority from a suspect backup.
- Selected-host directory-fsync fault injection, canary, restart, rollback and SLO receipts.
- Independent review, operator acceptance and release approval.

The detailed architecture remains in `TECHNICAL.md`; this projection records its current
source/execution boundary without replacing that design. See `EXECUTION_DOSSIER.md`.
