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
Serialization, crash/reopen, deletion rebuild, real encoder invocation and the
canonical wire-protocol adapter are still separate integration work.

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
