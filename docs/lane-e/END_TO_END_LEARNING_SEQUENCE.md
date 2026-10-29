# Lane E end-to-end learning sequences

This document names the linearization points and authority boundaries for the
four Lane E modules. It is an implementation map, not evidence that a product
caller, future-calendar outcome, independent operator or production deployment
exists.

## 1. Candidate decision to immutable dataset

```text
product host authenticates generator and immutable objective
  -> generator enumerates a bounded legal candidate set
  -> CandidateSetCompletenessReceiptV1 binds generator code, grammar,
     hard filters, deterministic truncation, canonical order and omission bound
  -> shadow or product policy emits one selected candidate and positive propensity
  -> LedgerWriter authenticates the generator and durably appends one immutable
     AuthenticatedDecisionV2 under the single learning.ledger owner
  -> effect owner or trusted observer authenticates independently from the generator
  -> AuthenticatedOutcomeV1 remains pending, censored or terminal according to
     OutcomeWatermarkV1; a Decision with no Outcome row is also counted pending
     at dataset freeze, and missing outcome never becomes zero
  -> LedgerWriter appends outcomes/corrections against the current linear
     predecessor head; stale branches and forks fail closed
  -> independent allocator finalizes one CreditAllocationBatchV1 whose
     allocations plus residual exactly equal the current terminal outcome, and
     LedgerWriter commits the whole batch as one durable event
  -> LedgerWriter derives source rows, eligible frontier, outcome watermark,
     correction cut and revocation/unlearning cut from canonical replay and emits
     the owner-native self-verifying DatasetSnapshotReceiptV3
  -> canonical cross-module publication uses the registered DatasetSnapshotV1
     compatibility adapter; V3 is not silently treated as an unregistered wire schema
```

Linearization rules:

1. Candidate completeness is checked before assignment and before the decision
   can enter an evaluable dataset.
2. A plain different string ID is insufficient for independence. Principal,
   credential-chain and signing-key identities must all differ and be current.
3. A terminal outcome requires an observed value and finalization time. A
   censored outcome requires a reason but no invented value.
4. Credit is published as a finalized batch. Individual allocations do not
   become authoritative before conservation succeeds.
5. Dataset freeze derives source rows and all cuts from current canonical replay;
   callers cannot self-report those frontiers. The owner-native V3 receipt is
   self-verifying, while the registered cross-module compatibility view remains
   `DatasetSnapshotV1` until a V3 wire schema is explicitly registered.

## 2. Dataset to operator and world-model candidates

```text
DatasetSnapshotReceiptV3
  -> independently recompute and verify the frozen DatasetSnapshotV2 identity
  -> require exact objective/dataset identity and exact source-record evidence
     equality before constructing an opaque verified training input
  -> fit_transition_model_verified_v2 builds an action-conditioned tabular
     baseline; relabelled duplicate evidence rejects before counting
  -> preserve the canonical DatasetSnapshotV1 exchange adapter and revalidate current objective, lineage and withdrawal state at final use
  -> unsupported state/action pairs return OOD instead of extrapolation
  -> validate_applicability_certificate performs structural checks only
  -> validate_applicability_with_signed_evidence_v2 additionally requires
     host-trusted generator/evaluator signatures and role/controller separation
  -> build_sensor_core deterministically selects a fixed farthest-point core
     and measures fill distance, separation radius and mesh ratio
  -> evaluate_bellman_reference requires a complete sensor/action grid and emits
     deterministic targets, greedy actions and action gaps
  -> verify_tabular_operator_plan_v2 binds exact frozen rows before
     fit_tabular_operator_verified_v2; canonical fit rejects duplicate evidence
  -> admit_operator_regularity performs structural regularity checks
  -> admit_operator_regularity_with_signed_evidence_v2 authenticates the exact
     assessment including dominant-component approval
  -> candidate bytes and the complete V2 manifest go to learning.artifacts
```

The existing `train` API is retained only as a compatibility alias for
`build_targets`. The direct fit APIs remain compatibility surfaces for already
trusted callers; new qualification code uses the receipt-bound V2 constructors.
An evaluator ID or credential digest alone is structural metadata, not authenticated
independence. Signed V2 admission authenticates the exact bytes but still does not
prove scientific validity, future efficacy or selection authority.

World-model predictions are always marked synthetic. They may support planning
or evaluation models, but they cannot become the independent factual outcome
that judges the same candidate.

## 3. Artifact publication and latest-head admission

```text
host authenticates a scoped withdrawal authority/domain/registry
  -> LearningArtifactManifestV2 binds bytes, datasets, complete lineage,
     predecessors, training code, runtime, device, objective, schema,
     normalization, compatibility, expiry and rollback predecessor
  -> admit_manifest_at_withdrawal_head_v3 binds the exact scoped withdrawal head
  -> ArtifactPublicationTransactionV1 begins at the exact V1 registry predecessor
  -> payload bytes are validated, created and synchronized
  -> transaction records PayloadDurable
  -> V1 compatibility registration is appended and its snapshot is durable
  -> transaction revalidates the live scoped withdrawal frontier, verifies the
     V1 projection and records RegistryDurable
  -> independent RegistryHeadWitnessV1 binds generation, predecessor head and
     authority epoch
  -> transaction revalidates the withdrawal frontier, verifies the exact witness
     receipt and records WitnessDurable
  -> final acknowledgement revalidates the current withdrawal frontier again and
     is permitted only from WitnessDurable
```

`DatasetWithdrawalScopeV1` binds `authority_domain_id + registry_id + scope_id`.
A scoped registry has a scope-specific genesis/head, and the scope digest is
included in V3 admission. An unscoped registry cannot issue a V3 admission and
cross-scope publication fails even when two scopes otherwise have equal event
content.

The V1 registry is a compatibility index. It cannot encode every V2 dataset,
lineage digest or predecessor. The publication transaction therefore keeps the
complete V3 admission as the authoritative V2 sidecar and checks only fields V1
can faithfully represent.

Readers must use a current independently retained head witness. A self-consistent
old snapshot is not sufficient. Generation rollback, authority-epoch rollback,
predecessor mismatch and expired current-head witnesses fail closed.

Publication is an ordered crash-recovery protocol rather than an assumed
distributed transaction. The host persists each transaction snapshot under its
writer fence before treating a phase as durable. A crash after payload
synchronization or registry publication cannot be relabelled acknowledged until
the exact witness phase is recovered and completed.

## 4. Evaluation and independent decision

```text
construct the complete EvaluationPlan before outcomes are inspected
  -> bind claim scope, candidate, baseline, objective, dataset, estimand,
     metric directions and safety floors, multiplicity, folds, final-holdout
     window and final-holdout digest
  -> freeze two or more cross-fold partitions into one sealed plan receipt
  -> every fold keeps training and holdout principal, episode and window
     lineages disjoint
  -> FinalHoldoutRegistry consumes that exact sealed plan receipt once
  -> fit nuisance model on training folds only
  -> compute OPE/sequential estimates and support diagnostics
  -> compute prespecified cluster intervals and multiplicity-adjusted evidence
  -> collect retention, subgroup, privacy and unlearning receipts
  -> decide_independently validates both receipt seals and their exact semantic
     binding, then verifies distinct principal, credential and signing key
  -> intersect candidate LCB versus baseline UCB, safety floors, support,
     multiplicity, snapshot count, future windows, retention and unlearning
  -> emit EligibleForIndependentSelection, Ineligible or InsufficientEvidence
```

An identical retry of the same frozen plan returns an idempotent holdout-use
receipt. Reusing a plan identity with changed semantics conflicts; a second plan
cannot reuse either the holdout digest or its final window. The deterministic
receipt seals detect in-process field mutation but are not signatures and do not
replace durable single-writer storage or authenticated issuer evidence.

`EligibleForIndependentSelection` deliberately grants no selection authority.
The evaluator cannot install, activate, merge, promote or release the artifact.

Resource ceilings are stage-specific:

| Stage                     |                                 Bound |
| ------------------------- | ------------------------------------: |
| Point OPE                 |                      `1,000,000` rows |
| Tabular temporal fold     |                        `100,000` rows |
| Composed temporal holdout |                         `16,384` rows |
| Sequential evaluator      | `4,096` trajectories / `65,536` steps |
| Sequential horizon        |                                 `128` |

A broad point-estimator bound must not be reused as the capacity claim for the
composed temporal pipeline.

## 5. Artifact lifecycle, load and rollback

```text
proposed -> trained -> evaluated -> shadow -> canary
         -> operator_accepted -> selected -> retired
any eligible pre-retirement state -> revoked
bounded early state -> quarantined
```

The producer may record training completion but cannot evaluate, accept or
select its own candidate. Each state change binds an actor credential, evidence,
authority epoch and time. Skipping mandatory states fails. New mutations
validate the actor at current time; historical recovery validates the same
credential at the immutable event occurrence time, so a credential expiring
after a valid event does not make old lifecycle state unrecoverable.

Selection is consumed by a different supervisor or selector trust domain. The
selector signs the artifact identity, exact authenticated CURRENT head/witness,
manifest lineage and payload bindings. `ArtifactSelectionVerifierV1` binds that
selector trust to the actual artifact-owner trust snapshot and rejects selector
keys reused by writer/head authority. Only then may
`record_verified_selection` persist the `OperatorAccepted -> Selected`
evidence and `load_selected_candidate` expose the exact immutable bytes.

A new process still revalidates CURRENT before each use. The old process retains
its immutable run snapshot. Rollback is a new independently signed selection of
an exact compatible predecessor; it is never implicit reuse of an expired grant
or stale backup marker. Revocation at a newer CURRENT head makes even a freshly
signed selection attempt fail before payload use. Canary, promotion and release
remain separately governed outcomes.

## 6. Correction, deletion and non-resurrection

```text
source owner supplies authenticated correction or unlearning authority
  -> for explicit unlearning, LedgerWriter verifies the exact historical
     DatasetSnapshotReceiptV3 and proves the named canonical source event is in it
  -> LedgerWriter persists source_event_digest + dataset_digest in UnlearningLineageV1
     and advances the correction/revocation cut without rewriting history
  -> artifact_id in the ledger event is only a handoff identity; learning.artifacts
     verifies the authoritative dataset→artifact relation
  -> scoped DatasetWithdrawalRegistry durably records the withdrawn dataset digest
     with a scope-bound canonical snapshot receipt
  -> all directly matching artifacts are revoked
  -> lineage eligibility makes descendants unavailable
  -> new artifact admission rejects every withdrawn dataset
  -> caches, indexes and projections invalidate by generation
  -> affected models are rebuilt without revoked inputs or remain revoked
  -> backup restore replays the current ledger and withdrawal frontiers before
     any restored bytes become readable
  -> independent unlearning receipt verifies zero resurrection
```

The persistent withdrawal registry closes the admission gap left by a
snapshot-local revocation batch: a later artifact cannot silently reintroduce an
already withdrawn dataset. Physical erasure, external caches and backup media
still require the responsible storage owner and independent evidence.

## 7. Crash matrix

Every state-changing adapter must test at least these boundaries. The
publication transaction has source regressions that recover from prepared,
payload-durable and registry-durable snapshots and prove that none can skip to
acknowledgement:

1. before local validation;
2. after validation but before durable write;
3. after payload or event synchronization but before registry publication;
4. after registry publication but before witness publication;
5. after witness publication but before producer acknowledgement;
6. after evaluation evidence publication but before independent decision;
7. after new-generation load but before route publication;
8. after route publication but before predecessor retirement.

Recovery uses the stable operation identity, semantic digest, exact predecessor
and current authority epoch. Unknown effects become pending, indeterminate or
quarantined; they are never relabelled success and never retried with changed
semantics.

## 8. Real neural model upgrade through the ordinary product path

This is the executable integration target of existing `NEU-1-LOCAL-MODEL-BAKEOFF`,
`LRN-1-DURABLE-EPISODE-LEDGER`, `LRN-2-CAUSAL-EVALUATION`,
`ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK` and
`INT-2-AGENTD-CODEX-COMPOSITION`; it does not replace their registered DAGs.
`learning-platform` owns training/ledger/artifact boundaries, qualification-plane
independently evaluates, intelligence-platform composes the existing ports,
agent-runtime hosts them and inference-platform owns real model execution.
The current tabular fit path in Section 2 remains useful reference evidence;
it cannot certify this neural target. A hash-derived encoder, scripted answer
lookup, synthetic GPU receipt or reference-only caller cannot satisfy it.

Use one identified pretrained neural backbone and bounded trainable head/adapter
with a real backend, exact weights, tokenizer, tensor layout, precision, runtime,
device and training code. Run at least three complete rounds; retain the complete
attempt lineage, including rejection, interruption and no-update. Each round:

1. Read back CURRENT/selected head and the actually loaded parent from the ordinary
   Neuron/inference caller; freeze release root, parameter hash, generation and
   objective. Revalidate withdrawal, current local authority/FinalUse, workspace
   and resource scope. Reconcile a selected/loaded mismatch before training.
   Training starts from those exact parent bytes; copied labels naming a parent
   are insufficient.
2. Ledger-owned authenticated decisions, independent terminal outcomes and a
   frozen dataset produce the next candidate off the current-run path. Bind the
   actual authorized task, consent/export scope and source lineage; secrets and
   unauthorized task data cannot enter a contribution or peer advertisement.
   Train real neural parameters only inside admitted bounds; create immutable
   manifest/lineage and bytes, with before/after tensor hashes and actual cost.
3. Before observing candidate evaluation outcomes, freeze the reproducible
   engineering evaluation plan and declared task bytes,
   versions, exposure/reuse and budgets. Public or previously seen tasks are
   admissible; unseen future data and independent data custody are not entry
   conditions for the three-round mechanism test. Preserve the existing evaluator
   and selector authority, credential and signing key, matched lifecycle cost,
   a frozen actual-parent baseline, best single expert, simple-merge and
   compute/data-matched adapter/full-tune controls where applicable. Compare the
   complete routed model as
   well as the changed Cell; test retention, safety, poisoning/backdoor, OOD,
   support and withdrawal. Existing causal/longitudinal estimators still apply.
   Ineligible/insufficient evidence takes the explicit no-update branch: record
   the decision, retain/revalidate the installed parent and prove its next-task
   use; do not run candidate selection or installation for a rejected artifact.
   Continue directly to step 6 using that parent; record unexecuted steps 4–5 as
   NOT_APPLICABLE with the decision reason in the versioned campaign record,
   without fabricating a task settlement, fetch or installation receipt or
   silently extending existing strict schemas. Reconcile any previously admitted
   Unknown effect under its original identity. This branch does not waive the
   separately required successful cross-node I09/I10 load-and-next-task cohort.
4. For an eligible update, submit only owner-approved task/evaluation/artifact
   references through the existing TaskFlow/PoN effect seam. Reconcile the exact submitted packet,
   task, output, active membership, depth and cumulative work under the original
   durable operation/outbox identity. Reorg changes that observation, not an
   already executed external effect or its retry safety. Chain settlement is a
   point-in-time observation; local acceptance/selection remains separate.
5. Fetch the complete selected release closure from another node, verify each
   dependency and safe loader compatibility, then perform authorized shadow and
   canary under current local install authority. Keep the still-authorized prior route available
   until the new loader has validated every required dependency and device
   allocation. A separate selector signs the current artifact head and exact root;
   the next generation loads those immutable bytes and publishes its route.
6. A subsequent ordinary task must execute that route and return an authenticated
   runtime/readback receipt tied to the same root, parent, generation and outcome,
   read from the real loader/session rather than copied from its request.
   Only that installed version may become the next round's parent. Crash/restart
   at any boundary reconciles existing owners rather than recreating a journal.

The cross-repository interface anchors are I06 export, I07 evaluation, I08 Chain
accepted-task observation, I09 release-closure fetch and I10 local installation
and readback in the [Chain plan](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/ef2a6958a6f3d8fdfaea25fbc58fb1ecd188134c/docs/development/TRNM_AI_NATIVE_BLOCKCHAIN_DEVELOPMENT_PLAN.md).
These are design-change anchors, not already deployed wire schemas. Preserve
`DatasetSnapshotV1` exchange, complete V3 admission, `LearningArtifactManifestV1`
compatibility and `EvaluationReceiptV1`/`LongitudinalEvaluationReceiptV1` meaning.
Register any new bounded adapter/schema and producer/consumer ownership before
implementation; bind parent/root, task/evaluation identities, dependency-closure
digest and loaded-root readback to the existing semantic digest. A receipt must
never copy its expected values from the untrusted observation it validates.

The following interface obligations refine those anchors through the existing
module ports. Field names are semantic requirements for a registered adapter,
not new accepted fields in V1/V2/V3 or a claim that an RPC already exists.

| Anchor / owner boundary                                                               | Request and independently checked result                                                                                                                                                                                         | Bounds and failure ownership                                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I06 contribution/export — ledger/plasticity/artifacts to the existing Chain task seam | Bind round, task/operation, installed parent, dataset/source/export scope, candidate/tensor roots and training/runtime version. Return immutable admitted contribution references and actual cost evidence, or a typed refusal.  | Freeze byte/count, CPU/GPU, memory/disk and duration limits before work. Source owners retain lineage and rejected/partial attempts; unauthorized export fails before network publication.                                            |
| I07 evaluation — artifacts/ledger to learning.eval and independent selector           | Bind candidate, actual parent, complete release closure, dataset, frozen plan/controls and evaluator/controller identity. Return signed measurements, eligibility/no-update reason and selection evidence with matching digests. | Bound evaluation/search/reuse and deadline; insufficient support, invalid provenance, poisoning or budget exhaustion cannot become an eligible release. The existing evaluator owns its receipt; the selector owns selection.         |
| I08 exact-task observation — existing effect owner to Chain observer                  | Bind original operation/outbox, packet/task/output and observation request. Verify block/state identity, membership, depth/work, verifier/trust version and observation time.                                                    | Bound bytes, query depth, retries and deadline. Unavailable, stale, reorged, rejected and Unknown remain distinct. The original effect owner reconciles possible dispatch; the observer never grants install/FinalUse or blind retry. |
| I09 release fetch — artifact consumer to Chain data-availability owner                | Bind immutable release/closure root, all dependencies, export scope and provider facts. Return verified chunk/object roots, complete inventory, bytes, source peers, timings and missing dependencies.                           | One shared fetch budget covers discovery, peer retries, partial bytes, hashing and repair. Data owner retains partial-download accounting; incomplete/unavailable/invalid content prevents I10 and does not change CURRENT.           |
| I10 install/readback — selector/artifacts to existing inference and runtime owners    | Bind selected root, expected CURRENT/predecessor, generation, compatibility and current local grant. Return actual loaded root/device/session and a later ordinary-task result under that same generation.                       | Bound decode, SSD/RAM/VRAM, startup/canary and next-task deadlines. Loader owns load failure; selector/registry own head changes. An uncertain install or possible effect reconciles in its original owner before retry or rollback.  |

Each adapter binds the original operation, paired source/profile, request/result
identity, semantic digest, expected predecessor/parent/release/task, contract and
local policy generation, finite CPU/worker/byte/disk ceilings and the original
absolute deadline. Results retain that identity, independently checked facts,
actual cost and completion/typed refusal or an explicit Unknown owner. Retry,
reorg and round re-entry cannot reset deadlines or accounting.
Unknown after a possible effect retains the original operation and reservation;
callers cannot erase it by starting another round. Publish measured costs and
terminal evidence through existing ledgers/receipts, without a parallel journal.
The original Hepta two-second read and 120-second startup contracts remain
fixed, as does Chain's absolute eight-second host/raw-U terminal boundary. The
existing Hepta Session shutdown observer separately retains its original
ten-second limit; this is not an extension or proof of Chain's eight-second
boundary. Model training/evaluation plans declare separate bounds.

Acceptance has two separate results. **Three-round mechanism closure** permits
no-update and proves correct training/evaluation/rejection, durable reconciliation
and continued task use of the unchanged parent. **Three beneficial releases**
requires three distinct accepted child artifacts, each independently exceeding
its actual installed parent's predeclared improvement threshold/confidence rule,
passing retention/safety/resource floors, being loaded, and serving the next
ordinary task. No-update, replayed outcomes or forced degradation of a baseline
cannot count as improvement. Preserve the existing requirement of at least two
calendar windows for longitudinal efficacy claims; a reused future holdout is
no longer future evidence. Engineering results are reported on the named test
dataset and do not imply generalization to unknown tasks. Independent future
data is not a blocker for this controlled mechanism test.

For each of the three cycles, retain one auditable join from ordinary task and
actual parent readback through authorized dataset, training, frozen controls,
evaluation and decision to the later ordinary-task readback. An accepted cycle
must include original I08 reconciliation and complete cross-node I09/I10;
a no-update cycle must prove the old parent actually ran and mark only the
unexecuted update stages not applicable. Three no-update cycles cannot satisfy
the separate successful transfer/install cohort or three-beneficial-release gate.
Inject loss/crash before and after export, settlement, fetch completion, CURRENT
CAS, route publication and next-task readback; neither missing receipt nor
Unknown can be filled with an expected-value echo. Final acceptance records
mechanism closure, transfer/install closure and beneficial-release count as
separate results in the existing versioned qualification record.

Retain exact paired commits, product caller, signed role/controller provenance,
model/tensor roots, datasets, sealed plans, raw measurements, task/effect IDs,
fetch/load/readback receipts, all failed attempts and rollback/restart records.
At least two distinct nodes must demonstrate real byte transfer and loading;
this controlled result does not establish decentralized public qualification.

The current controlled SmolLM2-135M five-control experiment is retained in
[`smollm2-five-controls-20261024.json`](../../qualification/learning-generations/smollm2-five-controls-20261024.json).
It executes the actual Chain `ef2a6958` strict-v1 CPU runtime: both loaders,
five training/control phases and all five evaluations complete with successful
original wait4/peak-RSS reconciliation. Candidate, fresh matched LoRA and matched
full-tune each score 1/2; the backbone and random control score zero. Gain against
the strongest control is zero, so no adoption or reward is justified. These
declared public smoke tasks supply reproducible engineering observations only.
Its `product_installation`, `three_round_closed` and
`network_transfer_integrated_with_loader` remain false; this documentation
refinement supplies no new run or status change.
The separate TCL4 release-profile transfer moves and rehashes 271,178,816 bytes
across three controlled nodes with the origin stopped before the second hop;
its [exact source evidence](https://github.com/TrillionniumFoundation/Trillionnium-Chain/tree/ef2a6958a6f3d8fdfaea25fbc58fb1ecd188134c/evidence/pon-upgrade-implementation-20261018/native-rounds/cell-tcl4-release-three-host-20261024)
fixes that transfer separately from the subsequent model execution.

The [controlled original-owner observations](../../qualification/learning-generations/real-model-owner-controlled-20261025/SCOPE.md)
retain three subsequent real parameter generations at the same Chain source.
Each generation loads its actual predecessor; all three training calls and all
three direct next-task forwards complete. These calls do not install CURRENT.
The original Hepta neural cases on clean source `07731d31` then actually pass
real-parameter artifact publication/recovery (1.094 seconds) and the complete
signed neural read/control/FinalUse/unload case (18.082 seconds). The original
gen2/gen3 comparison fails its unchanged 60-second nextest limit: its retained
journal contains 37 submits and 36 settlements, rather than the required 66
records. The original retry rejects the existing output; it is not a clean retry
or a passing result. The earlier archive setup failure dispatched no test and
remains separate.

The same unchanged signed neural case also passes in 17.753 seconds with the
actual peer-fetched model weights from that TCL4 release, using the separately
supplied controlled parameter adapter. This demonstrates actual loading and
inference over transported weights. It does not prove selection or installation
of a complete Cell release. Source-bound build/execution receipts, raw archives
and hashes distinguish these runs from the earlier five-control experiment.
The same compact observation files are retained in the Chain development-plan
evidence; they grant no new trust or admission authority.

A later [eleven-object controlled I09 observation](../../qualification/learning-generations/real-model-owner-controlled-20261025/i09-eleven-material-controlled-20261026.json)
on clean Chain `915f933c` / Hepta `da4a920` reconstructs all original TCM1/TCR1
bytes from one loopback peer and passes the original signed load/query/denial/
terminal-unload case in 10.133 seconds. Transfer and final readback take
3.240547 seconds within the original 35-second budget, separately from native
load. Three authorizer binding calls yield two durable nonce claims. Its
overall handoff still fails/exit1 at unavailable I10 selected installation;
ordinary-task forwarding, CURRENT installation, three installed-parent rounds,
funded resource return and independent custody remain open. The separately
source-bound `767d0f21` run passes five selected-initial cases and the original
gen3/gen1 signed cases within their original limits; it grants none of those
missing product qualifications. Earlier failures remain retained.

The separate [new-engine I09 run002](../../qualification/learning-generations/real-model-owner-controlled-20261025/i09-eleven-material-sqlite3513-controlled-20261026.json)
uses clean Chain `4c8c2ee7` / Hepta `8d25c5d7`, the SQLite 3.51.3 Cell binary and
fresh databases. The same eleven-object / 269-chunk fetch and readback takes
4.257683 seconds within the original 35 seconds; the original signed native
case passes in 10.357 seconds. Three authorizer bindings yield two durable nonce
claims. The overall controller still fails exit1 at I10 selected-installation
UNAVAILABLE. This does not relabel run001's `915f933c` / `da4a920` source pair,
qualify full PN1/SDK, or establish ordinary-task/CURRENT/three-round/WAN success.

The subsequent bounded parallel-start repair is actually tested on clean Hepta
`43ad626b` on the local ROG Linux CPU host. The same three original native cases
all pass: artifact publication/recovery in 0.239 seconds, complete gen2/gen3
comparison in 13.651 seconds and signed read/unload in 5.943 seconds. Both model
owners remain independent. All 32 tasks, 64 real forwards, 66 signed claims,
66 submit/reserve/assign/settle records, exact control cold reopen and both
terminal unload assertions pass within the unchanged limits. The original
runner returns `Ineligible` for `binary-correctness`, so no installation follows.
The [source-bound observation](../../qualification/learning-generations/real-model-owner-controlled-20261025/parallel-start-original-native.json)
binds the unchanged tensors and training receipts, explicitly relocated parent
descriptors with new hashes, original execution receipts and raw archive. That local
result is not a 4060 execution. The old
077 timeout, failed retry and setup observations remain retained.

The integrated source `b27a2f5e` is also tested using one frozen archive on both
hosts. The local ROG passes all three cases (0.240, 13.129 and 6.234 seconds).
After reconnection, the 4060 passes publication/recovery in 3.216 seconds and
signed neural read/unload in 29.451 seconds. Its comparison fails in 41.219
seconds: the first candidate query becomes `Indeterminate`, response send gets
BrokenPipe and the original supervisor fails. Its unchanged retry rejects the
existing output. Only three records per control phase survive; the required
66-record chain is not completed. The [paired observations](../../qualification/learning-generations/real-model-owner-controlled-20261025/integrated-b27-original-native.json)
retain both outcomes and original limits. Existing wall-clock timestamps fit a
query cutoff, but do not establish the exact earlier host-close cause or a
per-forward execution duration. No extra forward, warmup or output reset is used.

The original selection owner now validates the fixed canonical positive-zero
initial material and exposes `SelectedInitialSmolLmMaterialV1`. Each use keeps the
original signed/trusted-selector expiry, known revocation and fresh original-owner
CURRENT checks; failure is sticky. Its 124 package cases and a deliberately
broken trusted-expiry control are retained. The host source now composes a
distinct initial-only constructor and `with_current_initial_read` in the same
selected-material/session owner. It binds actual measured load/forward facts and
scores through the original signed control, FinalUse and nonce owners, with the
original two-second read window. A read-only callback sees historical evidence;
later failure cannot retract copied values or authorize ordinary-task effects.
The evaluated neural trait remains closed to this initial port. Its nine
original/new real-model cases are not yet qualified. After the retained missing
debug-directory preflight failure, the first original allocation built the full
current CLI from `155264e3b5` in 360.862 seconds, then failed host-library
compilation: seven ambiguous assertion references and one observer fixture missing
physical identity/scope. No test executed. The four-line source successor
`fa0ce3e02` preserves every assertion and supplies the existing fixture identity;
it is formatted but has not been recompiled or run. Both failures remain, the
original allocation is not restarted, and all nine cases and strict checks
remain NOT_RUN. This does not close model, Windows, ordinary-task or CI gates.
Agent-runtime must still compose the ordinary task context and exercise the
unchanged eligible-child, CURRENT, cold-recovery and three-round upgrade owners.

Learning-platform and agent-runtime must then compose the original ledger,
evaluation, selection, artifact/CURRENT and next-task owners in the order above.
First bind a genuine initial neural parent through the original selector and
CURRENT. The evaluated neural constructor still requires an eligible
SystemLongitudinal child; a Qualification comparison or an unselected trained
generation cannot supply that initial parent. Any genesis material prerequisite
must prove the actual fixed upstream roots and zero-effect parameters without
granting evaluation, selection or installation authority by itself.
The existing Chain PN3 plan now includes an explicit trainable-working-copy V2
preparation component (`scripts/llm_initial_trainable_setup_v2.py`). Copying the
canonical A=B=positive-zero parent otherwise leaves both LoRA factor gradients
zero. The component reads back that original parent, then restores the caller's
captured seeded A with B still positive zero; thirteen real small CPU Torch/PEFT
controls pass without skips, with the original nine tests and V1 assertions
preserved. Negative-zero-only A, overlapping factors/base/buffers, operator drift
and compiled dispatch are rejected before mutation. Its seed is caller-declared;
setup hash changes and algebraic B-zero preservation do not prove learning,
useful gain or full-model numeric preservation. The original runtime owner must
still bind this explicit recipe/source and actual predecessor into the same
training/evaluation budget and lineage, validate the full 135M model, and perform
ordinary installation and next-task readback. These controls grant no selection,
CURRENT, FinalUse, reward or three-round acceptance.
A later [single controlled V2 train](../../qualification/learning-generations/real-model-owner-controlled-20261025/initial-v2-controlled-train-20261026.json)
on isolated Chain `a23b5f2d` actually loads the 135M backbone and canonical parent,
validates the distinct new-task contract and completes ten optimizer steps in
the same original 1,800-second / 16-GiB supervisor. Setup changes only sixty A
factors, with B still zero; training then changes all 120 factors independently
of setup. Exact original wait4 and completion verification pass in 25.334008
seconds; the original missing-RSS reconciliation remains raw evidence. Fourteen
raw pins distinguish the thirteen result-tree files from the launcher stream.
This is unsigned train-only evidence in the current accelerate 1.15 profile,
not historical 1.12 equivalence, useful gain or full-model numeric preservation.
V2 evaluation/readback remain closed. Matched evaluation, owner-approved
selection, I10 installation and ordinary next-task/three-round composition
still require the existing owners; all qualification flags remain false.

A separate [candidate-only V2 observation](../../qualification/learning-generations/real-model-owner-controlled-20261025/initial-v2-candidate-observation-20261026.json)
on isolated Chain `0dcf8001` then loads that actual `a23b5f2d` trained 135M
candidate, reads back the original parent and all 120 candidate factors, and
executes eight tasks / sixty-four real forwards. The actual derived contract
`c9b06f9a` stays distinct from parent `2bb480a2`; no parent or task registration
is silently rewritten. Its original 600-second / eight-GiB supervisor reports
success and exact wait4 in 8.854378 seconds, with all seven stages and the
original missing-RSS reconciliation retained. This unsigned observer is a
separate explicit route: the parent-step V2 evaluate/readback dispatcher stays
closed. Outputs are engineering observations, not quality gain, FinalUse,
selection, I10 installation, CURRENT, ordinary next-task or three-round success.
The fixed V1 zero-parent profile and prior strict same-plan refusals remain.

The separate fresh native host raw-U observation still fails its original
eight-second cutoff; its post-deadline 4,096-byte kernel charge is diagnostic,
with the same original owner retained. Funded resource return remains open.
None of these component observations closes the three-round product target.
The original Hepta two-second read, 120-second startup and ten-second Session
shutdown observer remain unchanged, alongside Chain's distinct absolute
eight-second host/raw-U cutoff. The experiment's training/inference budgets
are separate and cannot replace any of them.

Reorg, withdrawal, lost acknowledgement, stale generation, restart after route
publication and unavailable replicas must preserve one logical operation,
reject revoked bytes and reconcile Unknown effects before any unsafe retry.

The same evaluated physical read now verifies its completed load and forward
against the original control journal before returning its observation. A private
single-assignment slot retains the actual successful load-settlement output;
this is distinct from the Ready JSON digest. The read joins the original
request, reservation, assignment, terminal digest and actual worker frame under
the original owner locks. It creates no new journal, grant, nonce or model call.
The cold-reopen control first requires a second live writer to refuse, releases
all original journal owners, then opens the same retained records again.
These source checks and additional controls are not compiled or executed model
qualification. The original nine model cases remain NOT_RUN; the earlier CLI
build and host-library compiler failure are retained and their original
900-second allocation is not restarted. Ordinary Agentd/AppServer provenance
propagation, selected installation, next-task readback and three rounds remain
open, with unchanged evaluated-selection gates and original time limits.

The initial-only query now uses the same private completed-record checker before
returning its existing observation. A borrowed source variant selects the exact
initial load domain rather than the evaluated load domain; the original query
payload remains on the executing stack. Missing, busy or inconsistent original
load/forward records close admission without another model call, nonce claim or
deadline. The original selected-owner association, CURRENT checks and read-only
callback remain unchanged. Added journal/wire controls are explicit fixtures
with no execution authority; neither they nor this uncompiled source step prove
model execution. The original allocation and nine NOT_RUN cases remain intact.
This prerequisite does not supply ordinary ContextV2/AppServer provenance, I10
installation or three-round acceptance.
