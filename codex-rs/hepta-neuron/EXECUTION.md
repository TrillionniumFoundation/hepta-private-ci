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
The composed owner path is `NeuronRuntimeHost`: it consumes canonical typed
Neuron inputs, invokes a required `FrozenModelExecutor`, validates the exact
weights/tokenizer/preprocessor/quantization/backend/device receipt plus native
runtime-binary, SBOM and license attestation, commits the sparse state through
`SparseJournal`, and advances a separately durable recovery witness before
acknowledgement. Strict canonical-JSON adapters exist for the
registered Neuron protocols. Segment rotation preserves the exact witnessed
checkpoint as genesis, and deletion rebuild replays only through the live lineage
policy; a failed rebuild is poisoned and cannot be reused.

The executor is an integration boundary, not evidence of a concrete local model.
The existing inference-worker model driver is still injected, so actual model
weights/device execution and target-host qualification remain external work.

## No manufactured intelligence evidence

Prediction error remains a bounded residual, not a manufactured uncertainty
estimate. The raw sparse receipt keeps `requires_calibration=true`; the canonical
host may clear the slow-path requirement only by applying a digest-bound,
generation-bound calibration/OOD artifact whose artifact, subgroup audit,
detector and support lineage are all currently admissible. Missing, expired,
OOD, low-confidence, collapse or resource evidence abstains. Every runtime result
remains `AuthorityPosture::DENY_ALL`.

Eligibility-to-parameter-group accumulation accepts samples derived from actual
`SparseCheckpoint` state and binds an independent-modulator evidence digest before
bounded low-dimensional modulation. It produces next-snapshot sufficient
statistics only; selected weights, topology and current-run artifacts are never
mutated. Real-model execution,
target-host resource measurements, ablation outcomes and longitudinal efficacy
remain external evidence, not consequences of unit tests.

## Verification and rollback

Run `just test --locked -p codex-hepta-neuron`, locked all-target compilation,
strict selected-package Clippy and formatting checks at both exact source and
actual-base synthetic merge. Tests cover canonical tie/order, inhibition,
homeostasis, L1 projection, signed rounding, clock/sequence/scope/config drift,
checkpoint corruption, extreme input and 2048-step bounded replay. Rollback
removes the additive export; the old API and callers remain unchanged.
