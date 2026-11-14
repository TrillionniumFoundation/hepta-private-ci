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
