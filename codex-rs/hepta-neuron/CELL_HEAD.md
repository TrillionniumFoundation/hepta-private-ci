# Shared Encoder + light Cell head

This slice makes the intended resource shape executable:

1. SharedEncoderOwnerV1::encode_for_cells calls the concrete Encoder once.
2. The result is one immutable SharedFeatureBatchV1, backed by an Arc<[i64]>.
3. Each Cell evaluates its own immutable CellHeadV1 against that shared feature slice.
4. The head emits bounded action logits, a value estimate, an uncertainty estimate, and an explicit abstain bit.

A head is bound to:

- one StableId for the Cell;
- one Encoder digest;
- one monotonic Generation;
- one canonical head digest;
- fixed input and action widths;
- Q24 affine parameters and a Q24 abstain threshold.

The first action_width affine rows are action logits. The next row is the value output and the final row is uncertainty. The implementation uses checked i128 accumulation, a fixed Q24 scale, parameter and output bounds, and fail-closed digest, generation, Cell-membership, and feature-width checks.

This is a deterministic baseline head and an ownership boundary. It does not claim that a head has been trained, that a learned gate exists, or that a System2/NDU capability has emerged. A future learned or nonlinear gate can replace the affine calculation while retaining the same shared feature artifact, per-Cell digest, resource envelope, and receipt boundary.

## Recorded FP64 learned Heads

The parallel `SharedLearnedFeatures770V1` / `LearnedCellHead770V1` interface imports
the actual recorded NumPy predictors without changing the Q24 contract above.
It is a fixed research profile: width 770, two classes, rank 4, and linear,
per-feature gated, or gated-plus-tanh-residual execution. It does not itself run
an Encoder or train a Head.

`SharedLearnedFeatures770V1::import` checks an independently supplied whole-file
SHA256, feature identity, generation, ordered source-record digests and the
1–64-row bound. It normalizes raw FP64 inputs once using
`x / max(sqrt(sum(x*x)), 1e-12) * sqrt(770)` and shares an immutable `Arc`.
Every Head borrows that same normalized allocation.

`LearnedCellHead770V1::import` checks the envelope, feature/generation/task pins,
and the original `NumpyCellHead.digest()` over dimensions, architecture, sorted
array names, shapes, little-endian FP64 dtype and every parameter byte. A width
match alone does not establish feature compatibility. This profile binds a
predictor and task; the caller's Cell registry remains responsible for assigning
that immutable predictor to a Cell identity.

| Head | Private FP64 parameter bytes |
|---|---:|
| Linear | 12,336 |
| Gated | 24,656 |
| Residual | 73,936 |

These are parameter payloads, excluding optimizer moments, metadata, inputs,
outputs and allocation overhead. The 64-row normalized feature tensor occupies
394,240 bytes once. Nonfinite parameters and intermediate overflows are rejected;
this accepted finite execution domain is stricter than allowing later clip/tanh
operations to hide an overflow.

`evaluate` returns raw logits plus feature/batch/task/predictor/generation
bindings. Calibration is unavailable, execution is `ShadowOnly`, quality remains
unqualified, and authority is `DENY_ALL`. There is no calibrated probability,
acceptance mask, action dispatch or promotion path in this API.

The bounded `learned_cell_replay` example reads externally pinned artifacts and
does not receive reference logits. See
`qa/stem-bakeoff/CELL_NATIVE_RESUME_PROTOCOL.md` and
`qa/stem-bakeoff/evidence/20261024-native-resume/README.md` for the measured source
version, actual learned-parameter comparisons, continuation evidence and limits.
