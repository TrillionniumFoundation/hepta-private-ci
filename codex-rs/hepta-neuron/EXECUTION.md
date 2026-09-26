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

`sparse_tick` is pure. Returning a successor does not durably commit it. The
V1 owner now uses three distinct durable boundaries: the sparse checkpoint
journal, the complete operation/result sidecar and the independent acknowledged
frontier. The sidecar freezes the complete runtime configuration and stores the
exact result before the journal commit, so restart, first-witness failure and
acknowledgement loss reconcile without model reexecution. Canonical checkpoint
predecessors are derived from committed state, not caller-authored summaries.
See [OPERATION_STORE.md](OPERATION_STORE.md) for the transaction and recovery
matrix.

The composing host still authenticates input provenance, enforces current
expiry/revocation and owns the files and directory durability. Concurrent pure
proposals may be computed, but only the host's single writer may publish one.
Product daemon activation, authenticated selected-artifact/current-owner wiring,
and independently qualified real-model execution remain separate
integration/evidence work.

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
checkpoint corruption, extreme input, 2048-step bounded replay, exact-result
restart, operation-store sync uncertainty, first-witness recovery, witness
acknowledgement loss and forged-predecessor rejection. Rollback must preserve
interpretability of both the sparse journal and operation sidecar; a predecessor
binary that does not understand `HPTNOP01` must not open or discard it.


## Versioned multi-population profile

The durable V1 `SparseConfig` format remains single-population and same-width so old journal replay bytes never change meaning. `PopulationSparseConfigV2` / `population_sparse_tick_v2` are a separate pure mechanism profile: temporal state is bounded independently from activation state, temporal-to-activation projection is explicit, populations form one complete non-overlapping activation partition, each population performs deterministic local top-k, and a bounded global top-k is applied only to those local candidates. V2 emits no authority and still requires independent calibration.

This V2 source implementation closes the mechanism-shape gap in the readiness target; it does not silently make the V1 journal capable of replaying V2 state. A production promotion to V2 requires a separately versioned durable encoding, owner migration/recovery tests, exact product composition, and target-host qualification.
