# Cell and Circuit contracts: engineering qualification

Baseline: `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` (`6ddfca24`).
Native library tests: **green-r3 PASS**. Scoped strict lint and formatting:
**maintenance-r1 PASS**. Tests and subsequent maintenance retain separate evidence.

This qualification covers owner contracts, durable recovery and explicit library
integration. It does not establish a production backend deployment, physical
weight sharing, throughput gains, training improvement or autonomous rollout.
Source paths below are relative to the repository root.

## Five implementation changes

| ID | Actual change | Principal source |
| --- | --- | --- |
| C1 | Cross-check baseline and candidate learning bundles against published state/output schemas and a declared encoder at selection, next-use and recovery readback. | `codex-rs/hepta-agentd/src/neuron_generation_update_adopted_learning.rs`: `validate_manifest_contract` |
| C2 | Protect original Circuit settlement slots from stopped polling and lease churn; reserve remaining obligations in legacy histories without rewriting replay. | `codex-rs/hepta-automation/src/circuit_journal.rs`: `persist_transition`, verified `load` |
| C3 | Bind signed terminal credit to the committed Circuit trace, original Cell decisions and the logical ledger/owner/episode identity. | `codex-rs/hepta-agentd/src/circuit_credit.rs`; `codex-rs/hepta-automation/src/circuit_store.rs` |
| C4 | Add explicit bounded Circuit-to-Cell batch execution using the existing queue, sealed admissions and independent per-item commits. | `codex-rs/hepta-agentd/src/circuit_cell_batch.rs`: `AgentdCircuitCellOwnerV1::execute_batch` |
| C5 | Persist original host queue measurements and reuse them during recovery; hold unmeasured work instead of understating cost. | `codex-rs/hepta-neuron/src/cell_batch.rs`, `cell_inference.rs`, `cell_owner.rs`, `cell_journal.rs`, `cell_journal_codec.rs` |

## Six-axis coverage

| Axis | Present at the baseline | Delta | Remaining boundary |
| --- | --- | --- | --- |
| Cell state/model contract | `CellCompatibilityBundleV1` pins base, adapters, composition, encoder, schemas, state semantics and training lineage; `CellDefinitionV1` binds the frozen runtime. | C1 | Readback validation is not a prepublication gate. Optional absent encoders retain their existing meaning. Base/adapter loading and update-rule correctness remain backend/artifact responsibilities. |
| Circuit execution | Typed schema pins, join waits, All/Any/Quorum, timeouts, child reservations, delayed bounded feedback, termination and causal traces already exist in `circuit_profile.rs`, `circuit_runtime.rs` and `circuit_join.rs`. | C2; C3 adds verified completion readback. | Finite history cannot support unlimited lease recovery. This profile does not add a general external-event or tool-effect executor. |
| Numerical/transaction boundary | Prepare/infer/decide/commit, dispatch admission, owner CAS, atomic policy/checkpoint records, witnesses and original-request readback already exist. | C4, C5 | Members commit independently. Unknown backend work or an unmeasured queue cost remains pending; recovery never grants redispatch. |
| Learning/credit | Signed independent outcomes, Pending/Censored/Terminal, conserved credit, correction lineage and partial-commit retry already exist in the learning ledger and intelligence closure. | C3 | This binds executed Cell-version targets to evidence; it does not implement a gradient, tool-attribution algorithm, reward evaluator or automatic training launch. |
| Shared inference/training | Frozen model pins, isolated Cell scopes, sparse kernels, `CellBatchQueueV1` and separate `CellUpdateBudgetV1` / `LearningIterationBudgetV1` already exist. | C4 connects Circuit admissions to that queue; C5 preserves cost across recovery. | No new physical shared-base allocator, production microbatch backend, scheduler or training budget policy is introduced. |
| Composition/lifecycle | Cutover plans distinguish Preserve/Reset/Migrate; lineage and rollback predecessors are pinned. Existing generation owners publish task-boundary resets and learning completes only after actual next-task use. | C1 tightens evidence for the existing reset-adoption path. | The Circuit registry still requires one common parameter bundle. Generic migration execution, mixed-version composition solving and atomic multi-Cell cutover are not added. |

Baseline contract sources include:

- `codex-rs/hepta-learning-artifacts/src/cell_bundle.rs`
- `codex-rs/hepta-learning-artifacts/src/learning_iteration.rs` and `learning_iteration_types.rs`
- `codex-rs/hepta-neuron/src/cell_types.rs`, `cell_update.rs`, `sparse.rs` and `population_v2.rs`
- `codex-rs/hepta-agentd/src/circuit_cell_binding.rs` and `neuron_generation_update.rs`

## Required constraints

- C1 validates shared semantic pins at learning readback. A changed weights digest
  alone does not prove that a trained base/adapter composition was loaded.
- C2 retains the existing history bound and canonical historical replay. Exact
  command retries remain readable. At most 63 tail lease transitions are allowed;
  legacy histories also reserve slots for their actual unresolved activations.
  Exhausted historical capacity or a later expired final lease is not repaired.
- C4 accepts 1-64 owner-issued admissions, at most one item per Cell scope.
  Only identical frozen runtime/bundle/schema groups share a numerical call.
  After admission fsync, the final guard rechecks both monotonic clocks, Circuit
  lease/run deadlines, Cell deadlines and queue age for the actual requests.
- C5 records the original pre-dispatch host queue sample after the backend call
  returns, including backend errors. Measurement is bound to scope, operation and
  full feature-request digest. The same value is idempotent; a different one conflicts.
  The queue calls `CellStateOwnerV1::record_host_queue_age`; admission reserves
  capacity for both measurement and eventual commit.
- New scalar admissions declare `Some(0)` host queue cost; batch admissions start
  at `None`. A crash before durable measurement leaves `UnmeasuredQueueCost` and
  pending state, with no result readback, redispatch, guessed zero or refund.
  Recovery waiting and measurement fsync are not charged as pre-dispatch queue time.
- New journal admission/cost tags prevent old readers from silently omitting cost.
  Complete legacy histories retain their recorded decisions; legacy pending
  admissions have unknown host cost and remain held.
- C3 uses the full original completion, including actual work and outcome.
  Signed evidence is passed unchanged to the existing ledger closure. The run-ID
  profile does not independently prove that a signed Decision was committed before
  dispatch, and identical ledger bindings denote the same logical domain.

## API order

1. For terminal-credit participation, open the intended `LedgerWriter` and derive
   `circuit_learning_run_id_v1(ledger, owner, episode)` before execution. Use that
   identity for `CircuitStartV2.run_id`, `CellScopeV1.run_id` and the signed
   Decision record. Existing runs cannot be relabeled into this profile.
2. Freeze the Circuit definition and `CircuitCellRegistryV1`. Create the durable
   run, advance it, construct each original Cell input and operation identity,
   then call `claim_circuit_computation` with its canonical Cell request digest.
   A cloneable dispatch DTO or `model_request_id()` is not execution authority.
3. Pass the sealed admissions and original inputs to `execute_batch`. The queue
   persists each new Cell admission before contacting the supplied batch port.
   Existing committed/pending operations use their original owner/readback path.
4. Persist each returned successful `CircuitCellExecutionV1.completion` separately
   with the current Circuit fence/CAS. Partial failures retain admitted pending work and
   observed cost; do not replace them with a fresh operation or execution claim.
5. After uncertainty, reopen the original owners and obtain
   `recover_circuit_computation`. Reuse the exact original inputs in `execute`
   or `execute_batch`; settle through Complete/Reconcile as the Circuit state
   requires. Recovery tokens do not authorize a new model invocation.
6. Once the run has a terminal outcome and no unresolved activations, call
   `terminal_credit_support` with the exact original input map. The method reads
   `bounded_circuit_committed_trace`, looks up original Cell receipts and compares
   the reconstructed complete receipts before exposing executed version targets.
7. Obtain independently signed terminal-outcome and allocation evidence naming
   that support and those targets, then call `append_terminal_credit`. The method
   rechecks owners, ledger/episode identity and objective before delegating to
   `append_outcome_credit_v2`. Retry the same identities after a partial append.
   Pending/Censored observations continue to use the existing observed-outcome API.

The existing `read_learning_updated_selection` and
`read_learning_updated_next_use` paths apply C1 automatically. They observe the
existing publication; they neither publish a bundle nor execute a migration.

## Native verification

The actual **green-r3** command ran from `codex-rs` with repository defaults:

```sh
just test --locked -p codex-hepta-automation -p codex-hepta-agentd \
  -p codex-hepta-neuron -p codex-hepta-learning-ledger --lib --test-threads 2
```

This combined run passed **1,060 active library tests**; **61 tests were skipped
by the default configuration**. Automation recovery, neuron journal/cost recovery
and agentd batch/credit/adoption cases passed inside this combined run. No three
separate targeted green command runs are claimed. Recorded identities and run
summaries are retained in [native_summary.json](native_summary.json).
The **green-r3** tested tree remains
`94eba9801f743fd0fe6c08444920f6677f4a2cfd`.

| Run or gate | Recorded result |
| --- | --- |
| green-r1, combined library run | FAIL: 1,049 passed; 11 failed because Joint helper metadata was missing |
| green-r2, combined library run | FAIL: 1,059 passed; one existing alias-race fixture failed its error assertion |
| green-r3, combined library run | PASS: 1,060 active tests, including all 16 new regressions below; 61 default skips |
| red-r4, baseline control | Five targeted cases: four expected failures and one historical-compatibility pass |
| Scoped strict lint, maintenance-r1 | PASS: command exited 0; no Clippy changes |
| Scoped formatting, maintenance-r1 | PASS: command exited 0; mechanical rustfmt changes only |

The **red-r4** tested tree was
`0da4f3416e3bfd3aedd92affdb39b8f37e866f87`. Its expected failures demonstrate
baseline gaps; its historical-compatibility pass remains a distinct observation.
Run subjects are retained as actually tested, not relabeled as a later commit.

After the test run, **maintenance-r1** completed these commands from `codex-rs`:

```sh
just fix --locked -p codex-hepta-automation -p codex-hepta-agentd \
  -p codex-hepta-neuron -p codex-hepta-learning-ledger --lib -- -D warnings
just fmt --base 6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5
```

The `clippy.patch` was empty (SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
Only mechanical rustfmt changes followed. Per repository `AGENTS.md`, tests were
not rerun after maintenance; the green result belongs to the tested tree above,
not to a later formatted or published tree.

The actual `hepta-joint-propose` helper was built independently from the current
staged candidate, located through Cargo's `compiler-artifact` metadata and pinned
for the attempt. Both `CARGO_BIN_EXE_hepta-joint-propose` and
`CARGO_BIN_EXE_hepta_joint_propose` pointed to that real artifact. This is not a
claim that the dirty candidate was a clean checkout of the baseline HEAD.

The existing alias-race fixture now explicitly sets test-file permissions to
`0600`, so the inode-alias check is reached independently of the process umask.
Its strict alias-error, unchanged-content and FIFO-rejection assertions remain.
The 11 missing-helper failures and the single umask-sensitive diagnostic are
retained as failed attempts; neither was converted into a passing result.

All **16 new regressions**, grouped by repository-relative source file:

- `codex-rs/hepta-agentd/src/neuron_generation_learning_contract_tests.rs`:
  `published_contract_mismatch_cannot_become_selection_or_recovered_next_use`;
  `backend_without_encoder_retains_its_explicit_optional_contract`.
- `codex-rs/hepta-automation/src/circuit_recovery_budget_tests.rs`:
  `stopped_polling_preserves_original_reconciliation_and_idempotent_retry`;
  `lease_churn_cannot_spend_pending_receipt_slots_across_reopen`;
  `historical_stopped_scheduling_events_retain_their_canonical_replay_semantics`.
  `codex-rs/hepta-automation/src/circuit_legacy_recovery_tests.rs` adds
  `legacy_stopped_history_reserves_actual_pending_settlement_slots`.
- `codex-rs/hepta-agentd/src/circuit_cell_batch_tests.rs`:
  `one_frozen_batch_keeps_scoped_state_and_ack_replay_independent`;
  `partial_batch_receipt_failure_recovers_only_original_pending_work`;
  `circuit_deadline_after_cell_fsync_prevents_batch_contact_and_reopens_pending`;
  `filtered_expired_member_does_not_block_live_request_after_fsync`.
- `codex-rs/hepta-neuron/src/cell_queue_cost_journal_tests.rs`:
  `unmeasured_admission_reserves_measurement_and_commit_and_measurement_is_bound`;
  `legacy_committed_history_replays_but_all_unmeasured_pending_history_holds`.
  `codex-rs/hepta-neuron/src/cell_batch_cost_recovery_tests.rs` adds
  `batch_queue_cost_and_policy_survive_native_errors_and_lost_measurement_ack`.
- `codex-rs/hepta-agentd/src/circuit_credit_tests.rs`:
  `terminal_credit_requires_both_owners_and_exact_original_inputs`;
  `circuit_credit_rejects_completion_bytes_without_matching_cell_readback`.
  `codex-rs/hepta-agentd/src/circuit_credit_signed_tests.rs` adds
  `signed_credit_rejects_cross_owner_ledger_episode_before_any_append`.

The cases use real owner journals, witnesses, SQLite replay and signed test
evidence where applicable; their model/control fixtures do not prove production
model loading or learning benefit. Existing optional learning/generation services
in `codex-rs/hepta-agentd/src/runtime.rs` are unchanged. This change adds no daemon
bootstrap or ordinary production caller for the new batch and credit entry points.
