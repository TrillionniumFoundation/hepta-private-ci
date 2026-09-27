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
| `CS-PUB-001` — A possibly published candidate is retained as indeterminate | `codex-rs/hepta-memory/src/cognitive_store_recovery.rs` | `codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs::post_rename_publication_failure_is_indeterminate_and_retains_candidate` | Source reconciliation injection; real target-fsync injection pending |
| `CS-AUTH-001` — Revocation prevents later writes without rewriting committed history | `codex-rs/hepta-agentd/src/cognitive_bootstrap.rs`<br>`codex-rs/hepta-memory/src/production_writer.rs` | `codex-rs/hepta-agentd/tests/cognitive_bootstrap.rs::signed_bootstrap_rotates_restarts_canaries_and_revokes_live`<br>`codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::revocation_after_commit_preserves_cut_and_rejects_next_mutation` | Signed and live-verifier fixtures; independently administered signer pending |
| `CS-ROLL-001` — Re-admission uses a fresh grant-bound writer generation | `codex-rs/hepta-cognitive-store/src/bootstrap.rs` | `codex-rs/hepta-agentd/tests/cognitive_bootstrap.rs::signed_bootstrap_rotates_restarts_canaries_and_revokes_live`<br>`codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs::fresh_generation_reopens_reconciled_cut_without_replaying_memory` | Repository restart/rotation; selected-host rollback pending |
| `CS-LIFE-001` — History and tombstones survive reopen without treating deletion as erasure | `codex-rs/hepta-memory/examples/cognitive_store_history_perf.rs` | `codex-rs/hepta-memory/examples/cognitive_store_history_perf.rs` | Measured owner history; pruning and physical erasure not claimed |
| `CS-EVID-001` — Current source and all required execution records are independently checked | `scripts/cognitive_store_map_verify.py`<br>`scripts/cognitive_qualification_manifest.py` | `scripts/test_cognitive_store_map.py`<br>`scripts/test_cognitive_qualification_manifest.py` | Exact source objects, no inherited success |

## Remaining external evidence

- Independent signer governance and retained current-cut witness outside the rollback domain.
- Trusted reconciliation of a commit-to-witness publication gap, without deriving authority from a suspect backup.
- Selected-host directory-fsync fault injection, canary, restart, rollback and SLO receipts.
- Independent review, operator acceptance and release approval.

The detailed architecture remains in `TECHNICAL.md`; this projection records its current
source/execution boundary without replacing that design. See `EXECUTION_DOSSIER.md`.
