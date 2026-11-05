# Sparse mechanism implementation boundary

This additive implementation is part of `BIO-1-ELIGIBILITY-HOMEOSTASIS` and
`NEU-2-TEMPORAL-SIGNAL-RUNTIME`, subordinate to the existing module guide,
`NEURAL_BIOMIMICRY_SPEC.md` and `NEURON_RUNTIME_EXECUTION.md`. It does not close
those entire packages or advance any capability/activation claim.

## Executable mechanism

`SparseConfig`, `SparseTick`, `SparseCheckpoint`, `SparseSignalReceipt` and
`sparse_tick` are exported from the existing `codex-hepta-neuron` crate.
The legacy Q32 `step` API is unchanged. Its `NeuronState` fields remain public
and mutable; the state digest does not authenticate edited values because the
record omits the original request and predecessor needed to recompute it. Hosts
must retain trusted outputs or verify their complete source history. Legacy
state is not a canonical recovery checkpoint and supplies no authority or
production-completion evidence. The new API uses signed Q24 only.

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

Owner calibration rounds residual penalties upward when converting to ppm:
confidence rounds conservatively downward and OOD conservatively upward. Exact
confidence/OOD thresholds remain eligible, while a residual just beyond a
threshold cannot be rounded into acceptance. The upper activity gate compares
the exact positive-unit count and vector width using integer cross-products;
the receipt's floor-ppm activity summary remains replay-compatible.
Qualification samples must retain
their exact candidate/source version. Samples computed with the earlier rounding
rule remain evidence for that earlier version; rerun qualification for this
candidate instead of relabelling those samples as updated results.

`checkpoint_bytes` is a conservative mechanism binary payload bound, including
the domain tag, all seven retained digests, sequence/time, projection metadata,
and five framed numeric vectors. It is not the canonical JSON DTO size, allocator
footprint or a measured disk write. The V1 journal persists tick/receipt frames;
`journal_bytes_written` and write amplification cover those frames only.

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

The 2026-10-01 audit adds explicit collection lengths to the pure V2 config
digest so projection, inhibition and population boundaries cannot be confused.
All prior pure V2 config/checkpoint digests change. Rebuild affected qualification
chains from a fresh sequence-1 checkpoint and rerun their evidence; never relabel
or inherit an old checkpoint. Durable V1 journal encoding and digests are unchanged.
