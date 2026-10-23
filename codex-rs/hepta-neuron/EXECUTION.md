# Sparse mechanism implementation boundary

This additive implementation is part of `BIO-1-ELIGIBILITY-HOMEOSTASIS` and
`NEU-2-TEMPORAL-SIGNAL-RUNTIME`, subordinate to the existing module guide,
`NEURAL_BIOMIMICRY_SPEC.md` and `NEURON_RUNTIME_EXECUTION.md`. It does not close
those entire packages or advance any capability/activation claim.

## Executable mechanism

`SparseConfig`, `SparseTick`, `SparseCheckpoint`, `SparseSignalReceipt` and
`sparse_tick` are exported from the existing `codex-hepta-neuron` crate.
The legacy Q32 `step` API is unchanged. The new API uses signed Q24 only.

The frozen external encoder/head supplies a drive vector. The kernel computes
`h_next = clip(rho*h + drive, -8, 8)`, subtracts registered lateral inhibition
from previous activation and the current threshold, and selects top-k positive
units. Ties use ascending unit index. Activity averages use binary unit activity;
thresholds follow the registered bounded homeostatic rule. The diagonal local
head's eligibility is `lambda*e + drive*activation`, radially projected into an
explicit L1 ball of radius 4. This is not a full dense weight-gradient estimator.
All products use i128 intermediates and signed nearest/ties-to-even Q24 rounding.

The kernel enforces 5..256 units, 1%..20% top-k, at most 4096 inhibitory edges,
nonnegative zero-diagonal inhibition with each target's incoming L1 norm <=1,
input/state range [-8,8] and bounded rates and thresholds. No production-profile
exception is added for the specification's two-unit explanatory example.

## Snapshot and host boundary

Configuration, model and normalization digests are fixed for a generation.
Sequences increase within that generation; the generation is not increased on
every tick. Scope and objective cannot change mid-checkpoint chain. Every state
binds its predecessor, clock, complete config and actual supplied numerical
input/prediction bytes, not just a caller-supplied feature digest. Checkpoint
fields are private; the state is returned only after full validation/computation.

`sparse_tick` is pure. Returning a successor does not durably commit it. A host
must authenticate input provenance, enforce expiry/revocation and CAS the exact
predecessor while atomically persisting the checkpoint and receipt. Concurrent
proposals may be computed; only the host's single writer may publish one.
Owner-local serialization, crash/reopen, deletion rebuild, exact inference-control feature execution and canonical JSON protocol adapters are now implemented on the closure line. Product daemon activation, authenticated selected-artifact/current-owner wiring, and independently qualified real-model execution remain separate integration/evidence work.

## No manufactured intelligence evidence

Prediction error is a bounded residual against a supplied frozen prediction,
not a trained world model or calibrated uncertainty estimate. Every receipt
has `requires_calibration=true` and `AuthorityPosture::DENY_ALL`. Consumers must
use the existing deterministic/slow path until an independently qualified
confidence/OOD adapter exists. No current weight, topology or artifact is changed.
Real model receipts, ablations, measured latency and longitudinal efficacy remain
external or later-package evidence, not consequences of these unit tests.

## Verification and rollback

Run `just test --locked -p codex-hepta-neuron`, locked all-target compilation,
strict selected-package Clippy and formatting checks at both exact source and
actual-base synthetic merge. Tests cover canonical tie/order, inhibition,
homeostasis, L1 projection, signed rounding, clock/sequence/scope/config drift,
checkpoint corruption, extreme input and 2048-step bounded replay. Rollback
removes the additive export; the old API and callers remain unchanged.


## Versioned multi-population profile

The durable V1 `SparseConfig` format remains single-population and same-width so old journal replay bytes never change meaning. `PopulationSparseConfigV2` / `population_sparse_tick_v2` are a separate pure mechanism profile: temporal state is bounded independently from activation state, temporal-to-activation projection is explicit, populations form one complete non-overlapping activation partition, each population performs deterministic local top-k, and a bounded global top-k is applied only to those local candidates. V2 emits no authority and still requires independent calibration.

This V2 source implementation closes the mechanism-shape gap in the readiness target; it does not silently make the V1 journal capable of replaying V2 state. A production promotion to V2 requires a separately versioned durable encoding, owner migration/recovery tests, exact product composition, and target-host qualification.

## Authority-free cell-state projection

`CellStateSplitPlanV1` and `CellStateSplitChildV1` provide the narrow state
projection needed by an external DecisionCell migration owner. A plan binds
parent/child identities, child scopes, an exact successor generation and
complete non-overlapping temporal and activation partitions. `SparseCheckpoint`
and `PopulationSparseCheckpointV2` can project recurrent temporal state,
activation, activity, thresholds and eligibility vectors into child payloads;
each payload binds the parent checkpoint/config/context digests and has its own
canonical digest. The operation is pure: it does not write a journal, advance
a witness CAS, select artifacts, alter routes, or issue authority. Cache,
optimizer and parameter-bundle policies remain in the semantic
`codex-hepta-types` cell-split contract and must be executed by their owning
migration/artifact stores.

`CellStateSplitPlanV1::from_contract` binds the executable Q24 partitions to a
validated `CellSplitV1` contract. For this kernel profile the recurrent and
eligibility transforms must be explicit partitions, the optimizer transform
must be an external-owner reset, and the mapping digests must equal the
canonical Q24 partition digests. This is a migration payload boundary; it is
not a checkpoint commit or a topology-application authority.

## Fenced multi-child state migration owner

`CellStateMigrationV1` wraps that projection in an owner-safe transaction. It
requires the parent `SparseCheckpoint` to match an independently acknowledged
`JournalAnchor`; a caller cannot start a split from an uncommitted or stale
parent. `persist_child_state` serializes exactly the projected Q24 vectors to a
host-created file and calls `sync_all` before returning a
`CellStateCasReceiptV1`. `record_payloads_durable` accepts the complete child
set only when every operation id, parent anchor, fence, payload digest and
encoded size matches.

The transition to `ChildrenCommitted` requires an external multi-file commit
witness containing every child receipt. Only then can `acknowledge` produce a
`CellStateMigrationReceiptV1`; callers must consume that receipt before fencing
parent retirement or route activation. Any child failure can move the whole
operation to `Quarantined` and then `RolledBack`, which returns the parent cell
identity as the rollback predecessor. The module does not claim that an
external witness, signed lease, directory sync or product route cutover exists;
those remain target-host evidence obligations.
