# Local native learned Heads and complete Adam continuation

This phase continues from `56b5815a8ae811f6846e92dbbe46ca1a74d83f2f`.
It preserves all earlier quality results and excludes remote CI. It addresses
two concrete remaining implementation gaps: lossless import of real FP64 Heads
into the actual Rust neuron crate, and continuation of complete optimizer state.
Neither result grants task-quality, calibration, action or production authority.

## Shared immutable inputs

Use the already sealed 770D bundle with manifest SHA256
`266af205b6053df3c3968d2de52ff6ede8d8ebc6add3909fa7bc081cd52a6fdc`.
Its feature identity is
`00b09d213137fd60d33b39761d462f69b6e692155f51b7efd77896911cbd62c0`.
Serving uses its original 64 source-hash-selected rows and 27 frozen Head states;
training uses its original seed7/n32 TRAIN bank, 32 different bug groups and
16 labels per class. Historical input reuse is systems regression, not a fresh
quality test. Do not fit calibration, read new holdout outcomes or call an Encoder.

## Native learned Head boundary

Keep the existing Q24 `SharedEncoderOwnerV1` and affine `CellHeadV1` unchanged.
Introduce a parallel bounded FP64 import/readout in the real `codex-hepta-neuron`
crate. Converting the existing weights to Q24 or float32 would change the
predictor, so it cannot be presented as exact import.

The feature artifact has magic `HEPTA-CELL-FEATURES-770-F64-V1` followed by a NUL,
then feature identity (32 bytes), generation (u64 little endian), row count
(u64 little endian), ordered source-record digests (32 bytes each), and the
row-major raw FP64 values. Allow 1..64 rows, width exactly 770. Cast original
float32 values exactly to FP64; do not change source order or reconstruct inputs.
Validate the complete externally supplied artifact digest before decoding and
bounded allocation. Reject nonfinite/overflowing values and invalid identities.
Normalize once with the frozen L2-times-sqrt-width rule; store the immutable
normalized bank for multiple borrowed Head evaluations. This import does not
claim to execute the shared Encoder itself.

Head magic is `HEPTA-CELL-HEAD-770-F64-V1` followed by a NUL. Then encode mode
(u8: linear=0, gated=1, residual=2), feature identity (32 bytes), generation
(u64 little endian), task digest (32 bytes), predictor digest (32 bytes), and
original FP64 parameters in lexicographic name order. Shapes are fixed by
width770/classes2/rank4: linear W,b; gated W,a,b,g; residual U,V,W,a,b,g.
Task digest is SHA256 of UTF-8 `action_usefulness`. Caller-supplied expected
artifact/feature/generation/task/predictor identities are independent inputs.
Recompute the Python `NumpyCellHead.digest()` recipe over dimensions, mode,
rank, array names/shapes/dtype and exact little-endian bytes.

Evaluate all 27 original states against the same native feature bank. Compare
every raw logit with the unchanged NumPy scalar predictor, with predeclared
absolute tolerance 1e-9 and matching argmax classes. Preserve max errors and all
per-Head output digests; do not claim cross-language bitwise floating arithmetic.
Exercise stale pins, corrupt/truncated arrays, wrong task/generation, altered
source identity, nonfinite inputs and resource bounds in focused tests. Native
output remains explicitly raw and uncalibrated, `SHADOW_ONLY / DENY_ALL`; it
does not import bounded calibrators or manufacture acceptance/action masks.

Compile and test the actual Cargo crate and real dependencies from the pinned
workspace using the repository `just test` entry point. A standalone mock or a
copy with substituted dependencies is insufficient. Record toolchain, lockfile,
source and executable identities and all build/test attempts. Sharing an existing
download cache does not establish its historical download cost as zero.

## Complete optimizer continuation

Keep frozen legacy numerical modules unchanged. A new resumable controller may
reuse their gradient and initialization code but must preserve the old Adam
constants, clipping, parameter order and microbatch-major update order.
Persist parameters, both moments, per-Cell step and current microbatch cursor,
input raw/normalized/index tensors, labels, ordered source identities, task,
feature, generation, parameter schema, optimizer configuration, and code/runtime
identity. This fixed full-batch training has no random minibatch sampler; record
that fact and the exact update order rather than inventing sampler state.

External checkpoint manifest and input/plan identity pins are required on load.
Validate archive member/NPY headers, dtypes, shapes and total uncompressed byte
limits before allocation. Checkpoints must be new ordinary artifacts; changes
to optimizer state, labels or provenance cannot bless themselves. Resume is
only at completed update boundaries, with no assertion of power-loss atomicity.

Before real execution, append an exact run plan after the implementation API is
fixed: three structures, the same frozen TRAIN bank, distinct per-Cell seeds,
20 steps, microbatch8, a small bounded cohort that crosses a partial final block,
and predetermined interruption points inside and between blocks. Compare
uninterrupted and fresh-process resumed parameters, both moments, steps and
trajectory records. Require exact equality for the same new implementation;
also compare the uninterrupted result with legacy microbatch training under
the previously fixed atol=rtol1e-10. Count all actual updates and failed work.
No new learning-quality statement follows from trajectory equality.

## Evidence and closing

Retain original inputs, states, failures and outer process costs. Separate
source preparation, compilation, training, native prediction, serialization,
recovery and publication. Nested timings are diagnostic breakdowns, not extra
cost. Unknown cost remains unknown. Freeze numerical code before the real runs;
retain its exact Git identity even if the required final formatter changes layout.
Perform a fresh-process artifact replay, then the repository-required final
formatting without rerunning tests afterward. Report native inference eligibility,
optimizer continuation eligibility and scientific task quality separately.
