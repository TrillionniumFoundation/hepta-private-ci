# H2: read a settled provider absence after its run lease has been cleared

## Fixed source and scope

Base: Hepta H1 `9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`, tree `24804b21d0306b617e12fa3f5b9454a12ed4ad41`, still bound to Chain C4. This directory contains five selected exact source paths, not a complete checkout. H1, its original two PQ test functions, the V12 source manifest, dependencies, and budgets are unchanged. No external effect or operator trust material is created.

The reviewed candidate is `settled-absence-v3.patch`; the prior v1/v2 drafts are retained. `patch-manifest-v3.json` records every old/new blob and SHA256. v2 replaces test SQL variables with literal SQL calls; v3 adds persistent hosted CI coverage. Neither changes the production design. Source review, `git apply --check`, and four synthetic exact-name CI guard controls are the only validation completed here. Rust formatting, compilation, and native qualification remain pending.

## Actual H1 failure

H1 `effect-pq-owner` ran 11 tests: 9 passed and 2 failed. The generation-change and signed-revocation controls passed their boundary-call and consumed-nonce assertions before failing in subsequent reconciliation with `TaskFlow owner id is missing`. `BeforeProviderContact` had already appended the absence proof, reconciled the step to `Cancelled`, and requeued the run to `Queued`, clearing its lease. The existing early fact reader supports successful/failed outcomes only. The host consequently tried to reconstruct a current owner fence before observing the already settled absence.

This is a production read-path gap. The original `prepare_effect` fixtures do claim/start the run and prepare/claim the step. The real-process fixture in `tests/support/automation_effect_operator.rs` also performs those steps (run claim followed by Start, then step prepare/claim); it needs no fabricated owner repair. The real-process gate was not reached in H1 and retains no native pass credit.

## Change boundary

* `authorized_effect.rs` adds `read_settled_authorized_taskflow_effect_absence`. It first requires the durable provider observation to be `ProvenAbsent`, then requires its immutable step intent, payload, exact cancellation command and proof to match the original occurrence. It returns a receipt as a local fact; no authority token or lease is issued.
* `taskflow_step.rs` shares the existing immutable run/definition/step-chain verification and adds a dedicated absence read. In the same SQLite read transaction, it locates the exact historical `requeue-absent` event, rejects duplicates, compares the transition/proof, and recomputes the original `TaskFlowCommand` digest from the old step fence, event revision minus one, and event timestamp. Checked conversion/subtraction rejects invalid numbers. The original fenced and completed-run decision block is byte-identical.
* `automation_effect_host.rs` consumes that verified absence before constructing a current run-owner fence. Unknown or partially projected observations still take the original current-owner/PQ reconciliation path. No provider call is made by this early return.
* The existing owner-recovery integration module receives exactly two additional controls. Its original test is unchanged. The two original Agentd PQ controls are not edited.
* `.github/workflows/hepta-pq-policy-renewal.yml` adds an independent two-case `effect-settled-absence` step and both exact names to the no-skip guard, for 69 original plus 2 additional selected tests. All original test commands, budgets, matrix lanes and the 90-minute total remain unchanged. The existing 1200-second scoped linter adds only the newly modified `codex-hepta-automation` package. The new step uses the original wrapper with 600 seconds, locked dependencies, zero retries and one test thread; the existing 60-second per-test configuration is unchanged.

The provider observation is read first by `effect_dispatch_attempt` in its own transaction. Step/run/event history is verified in a later shared read transaction. Stability between those snapshots relies on the existing terminal `ProvenAbsent` observation and append-only rules: a terminal observation cannot become a different outcome or receive another reconciliation. This patch does not make the whole effect ledger/step/run read one transaction and makes no cross-store atomicity claim.

The read is deliberately a historical fact read: a legitimate newer claim or running generation does not erase a prior settled absence. Current `Queued` state alone is never evidence. The implementation recognizes the authorized-effect requeue settlement path; it does not generalize arbitrary cancelled runs, scheduler cancellation, provider NotFound, or uncommitted projections into absence. Original redispatch, lookup, and mutation rules retain their owner and current PQ fences. The on-disk schema and signed message domains are unchanged.

## Additional controls to register and execute

Cargo package `codex-hepta-automation`, integration target `authorized_effect`:

1. `owner_recovery_tests::settled_absence_fact_read_survives_reopen_and_new_owner_without_redispatch`: direct pre-contact absence and unknown-to-owner-proof both settle, clear the old run lease, survive store reopen, remain readable after generation 2 claims/starts the run, do not change that new run, and cannot redispatch the old attempt. Driver contact count and consumed nonce remain one.
2. `owner_recovery_tests::settled_absence_fact_read_rejects_unknown_unsettled_and_corrupt_evidence`: unknown remains unreadable as absence; an injected failure of the actual run-requeue INSERT leaves a durable absence observation and cancelled step but no settled fact; independent fixtures then corrupt proof, intent, payload, step fence, and the legacy run-event timestamp. The timestamp case must reach the new exact command/fence mismatch, not merely an unrelated old hash check. Every mutation first proves that the immutable UPDATE trigger refuses the same literal statement before explicit fault injection.

These are automation owner/store controls using the pre-existing explicitly classical test fixture. They are not PQ qualification. The unchanged Agentd two regressions, original selected 69 controls, real Agentd process kill/drop-ACK control, and remaining original gates must run on a new committed H2 source under their unchanged limits; H1 pass receipts cannot be transferred to H2. No new evidence-lib test is added, so the expected full-evidence active inventory is not changed by this patch.

## CI source validation

`check_ci_candidate.py` parses the exact H1 and candidate workflows and verifies that every pre-existing test step is equivalent, its relative order is preserved, the four-lane matrix/environment/90-minute limit is unchanged, and the original selected-name set is a strict 69-case subset of the new 71-case set. `ci-static-controls/proof.json` records one complete-inventory acceptance and three required refusals: missing new receipt, ignored new case, and duplicated new case. Their logs are explicitly synthetic name-guard fixtures, never native execution receipts.
