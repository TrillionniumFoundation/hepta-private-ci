# Cell framework refactor: source and qualification boundary

This candidate extends the fixed integration base
`07378034e060f23259bc99c7367f12b1284140f3`.
The review branch is `codex/cell-framework-20261105`, stacked in PR #4887
on integration PR #4855. The source changes have been saved and read back through
GitHub. No Rust compilation, formatting, Clippy or test execution has completed
for this candidate. This record is not an acceptance or deployment receipt.

## Source ownership and implemented paths

| Requested change | Source capability | Existing owner retained |
| --- | --- | --- |
| Native Cell interface | Frozen prepare/encode, durable inference admission, exact receipt verification, masked decision, state/receipt commit, immutable update proposal | Neuron state owner and shared inference.control |
| Bounded Circuit runtime | Explicit bounded_feedback_v2, delayed feedback, reactivation, child programs, All/Any/Quorum join, finite causal trace and hierarchical budgets | Existing per-Agent AutomationStore |
| Learning coordination | Seven receipt-driven stages, pinned owner evidence, bounded Agentd workers, real terminal-value trainer and existing proposal producer | Existing ledger, artifact, Memory, proposal and selection owners |
| Compatible publication | Full component/lineage bundle, sealed scoped cutover, explicit Preserve/Reset/Migrate and exact owner readback | Artifact and temporal-state owners |
| Structural lifecycle | Durable stop-admission/drain/fence/transfer/publish/readback/resume intent and observation journal, attempt-bound recovery and independent anchor CAS | Existing control/FinalUse/physical topology owners |
| Shared compute and state partitioning | Bounded microbatch port, per-request result binding, agent/cell/run/principal partitions and one shared journal/facility | Existing process, model facility and durable state ownership |

The Cell entry points are exported from `hepta-neuron`:
`prepare_cell_step`, `enter_cell_step`, `infer_cell`,
`recover_cell_inference`, `decide_cell`, `commit_cell_step`,
and `propose_cell_update`. The inference operation has a stable scope/operation
identity and a separate full semantic request pin. A snapshot or deadline change
cannot mint a second model execution for the same operation.

`AgentdCircuitCellOwnerV1` shares one state owner, encoder facility and model
control port across its immutable Cell registry. It consumes only the
non-cloneable, non-deserializable admission issued after the real AutomationStore
commits its computation claim. Raw dispatch DTOs cannot enter this composition.
The claim binds the exact downstream Cell request, including original clocks,
frontier, objective, NDU snapshot and candidate mask.

The bridge's final control-port guard rechecks Circuit lease/run limits and the
Cell deadline after durable admission and immediately before model contact.
Both time lanes are checked for regression through decision and commit. The batch
API requires a live clock provider, rechecks after all admissions are persisted,
and retains expired items as pending without sending them to the backend.

The bridge returns a Circuit completion only after the Cell state owner commits.
A lost completion acknowledgement is read back from the same Cell operation.
Reconciliation-only admission prohibits new encoding/inference dispatch when no
prior admission exists. An existing pending inference is recovered by reading the
original control request and verifying its complete receipt.

The semantic output excludes operation IDs, checkpoints and cost. The separate
completion receipt binds all of those audit fields. A new audit identity alone
therefore cannot manufacture circuit progress. No-progress counters are per
(instance, node), including subcircuit return. Completed joins expose canonical
reference-envelope bytes through the verified AutomationStore; their public
schema is explicitly matched by the next Cell's input. Work has an explicit unit in this
bridge: model latency microseconds. Memory, checkpoint, truncation and queue
metrics remain separate fields in the full receipt. Actual work above a
reservation is charged in full; the Circuit takes WorkBudget fallback and keeps
other unknown reservations.

## Real terminal-value training profile

`terminal_learning_channel_v1` and
`AgentdConfig::with_terminal_learning_bootstrap` attach an explicit supervised
native profile. The host supplies its retained shared `LedgerWriter`, existing
Memory Replay consumer, fixed producer/Agentd generation, and independently
evaluator-signed `DatasetFreezePlanV2`. The worker verifies the independent
ledger witness and current Replay permission, then calls the actual
`LedgerWriter::freeze_dataset`, `freeze_terminal_cell_from_owner_v1`
and `fit_terminal_cell_from_owner_v1` paths. It returns a real tabular payload,
dataset receipt, source lineage and elapsed work under DENY_ALL.

This supports the existing constant-state, common-run/objective/action-set
terminal-value profile. It does not convert a tabular candidate into a generic
neural/LLM compatibility bundle, publish it, select it or claim next-task adoption.

The implementation bounds its queue (1..64), retained jobs (1..16, no eviction),
native compute permit (one), ledger/dataset records (at most 4,096), actions
(at most 128), artifact bytes (at most 1 MiB), and requested wall budget
(1..60,000 milliseconds plus an absolute deadline). The actual blocking job keeps
its permit through timeout/cancellation. Atomic fit cannot be preempted;
over-budget output is rejected and native work may finish after its waiter exits.
No mutex guard spans an await.

Within one owner lifetime, retries bind the entire canonical request, dataset,
profile, budget and evaluator evidence. Completed candidates are read back with
current Memory/ledger/trust revalidation without refitting. The job cache is not
durable: a recovered ledger does not reconstruct a job outcome, and missing
readback returns CommitUncertain. An explicit new training submission after
restart can repeat read-only computation. This is not cross-restart exactly-once.

Four new tests use actual Memory and authenticated LedgerWriter fixtures for
freeze/fit/payload prediction, readback and revocation, evidence/budget denial,
bounded queues/lost acknowledgement, and recovered-ledger/unknown-job behavior.
They are authored and have not run.

## Recovery and publication invariants

- TaskFlow V1 DAG validation, timer ownership and legacy wire semantics are unchanged.
- Circuit definitions and Cell parameter/runtime bundles are immutable per run.
- Circuit history is replayed and checked against its projection before use; arbitrary deserialized runtime projections are not trusted.
- Cell inference admission is flushed and independently anchored before dispatch. The final state/decision commit clears pending in the same journal record.
- Unknown, missing, failed or cancelled model receipts do not prove no contact and do not permit redispatch.
- Admission/readback/decision/commit times must be nondecreasing. Late admitted work settles its actual cost and commits abstention.
- Every lifecycle pending intent reserves its future observation slot, including against writes by other operations and the per-operation history cap.
- Lifecycle no-contact observations bind the precise durable prepare revision and attempt digest. A receipt from an earlier attempt cannot clear a later pending attempt.
- Database commit without independent anchor acknowledgement is uncertain. Recovery validates the original record and current trust before advancing the anchor.
- Cutover readback binds the principal/agent/cell/run partition, plan, generation, bundle and checkpoint. Binding checks are not a substitute for the state owner's authentication.
- All Cell decisions, update candidates and lifecycle intents retain DENY_ALL. External effects remain behind their existing FinalUse and custody boundaries.

## Native validation status

The fixed source checkpoint is `217ab49d9688b506088e094ff83437231ee605df`. The final
candidate contains **110 newly authored test functions** across
12 new test files. They are source test cases, not executed test results.

| Scope | Authored tests |
| --- | ---: |
| Native Cell, inference and journal | 35 |
| Circuit reducer, durable store and sealed admission | 36 |
| Compatibility bundle and generic iteration core | 10 |
| Agentd generic iteration composition | 5 |
| Agentd real terminal training profile | 4 |
| Agentd Circuit/Cell composition | 10 |
| Structural lifecycle journal/recovery | 10 |

**NOT RUN.** The execution environment became unavailable. The separately opened
cloud task could not fetch its integration base because its configured proxy
connection failed. GitHub source operations remained available.

The workflow `.github/workflows/hepta-cell-framework-native.yml` checks out
the exact source SHA. Its two lanes cover the mechanism crates and Agentd
composition, retain real runner receipts, require at least one executed native
test, and run strict Clippy. Queued jobs, generated source, static inspection and
fixture construction do not count as passing native tests.

The required native commands are:

```bash
just fmt
just test --locked -p codex-hepta-neuron -p codex-hepta-learning-artifacts -p codex-hepta-automation -p codex-hepta-runtime -p codex-hepta-control-plane
just test --locked -p codex-hepta-agentd
just clippy --locked -p codex-hepta-neuron -p codex-hepta-learning-artifacts -p codex-hepta-automation -p codex-hepta-runtime -p codex-hepta-control-plane -- -D warnings
just clippy --locked -p codex-hepta-agentd -- -D warnings
```

Use the repository runner and pinned toolchain/dependencies. Required integration,
architecture/document and target-host gates also remain outstanding. No Cargo
dependency or Bazel lock update was introduced by this refactor.

## Remaining implementation and deployment boundaries

1. **Ordinary product composition.** The Cell/Circuit facility and learning workers
   require explicit owner bootstrap. They are not automatically enabled for every
   Codex/App Server turn. Concrete encoders and inference request readback must be
   supplied by the existing shared facilities.

2. **Generic learning closure.** The seven-stage worker has an actual proposal
   caller and pinned evidence verifier, but the generic experience/dataset/trainer,
   durable iteration checkpoint, selection and actual next-task providers still
   require production implementations. In-memory fixtures are not durable
   production coordinators, and a signed nonzero digest is not by itself an actual
   training or next-use observation.

3. **Physical structural lifecycle.** The new lifecycle journal coordinates and
   verifies intent/observation transitions. It does not itself stop real traffic,
   fence a physical writer, migrate live state, install a bundle or restart an
   organ. The existing public Cell lifecycle admission hold is preserved until
   the actual control/FinalUse/physical owner chain is qualified.

4. **Unknown-outcome liveness.** If a Circuit claim is committed but lost before
   the Cell receives it, recovery remains readback-only. Missing Cell state is
   not proof that a former worker cannot still contact inference. Likewise,
   failed/cancelled/absent Cell readbacks retain pending state. A future explicit
   fenced no-contact or terminal failure-cost settlement profile is needed for
   those cases; this candidate does not silently reopen them.

5. **Bundle/state activation.** The Cell journal's partition admission table is
   frozen. Dynamic membership, changed bundles/schema and migrated/reset state
   must be installed by the admitted lifecycle/state owner. A cutover plan or
   split/merge proposal alone does not perform that physical transition.

6. **Independent custody.** Journal/anchor APIs and tests preserve the separation
   contract, but only target-host evidence can establish physically independent
   rollback domains, current observer trust, live fencing and forced recovery.

7. **Performance and useful learning.** The source supports shared compute and
   bounded microbatches. It has no new throughput, tail-latency, memory, learning
   gain or retention benchmark result. Circuit mutations currently replay bounded
   canonical history, so long histories incur repeated replay cost. Any future
   cache/checkpoint optimization must retain the same verification boundary.

The PR remains a draft source candidate. Production acceptance, activation,
promotion and release have not been granted or demonstrated.
