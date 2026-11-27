# Corrected-lineage N256 first-step full-state contract

Status: **HOLD / SOURCE_ONLY / NOT_EXECUTED**.

This package freezes a separate bounded experiment that may advance the
authentic corrected warm `t=0` capsule from Draft #6609 to warm `t=.001`.  The
target is the existing authentic roster entry with capsule identity
`af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1`:
69,728 FP64 coordinates comprising 2,600 state coordinates and 67,128 packet
coordinates across nine packets.

The future candidate and independent numerical oracle do not exist in this
source-only stage.  Their hashes, the execution admission, idempotency key,
runtime, host, ancestor-cgroup snapshot, allocation and calendar therefore
remain `null`.  No numerical import or execution is permitted by this change.
The future envelope is limited to one candidate step with at most two sparse
matrix-exponential actions and one independent oracle step with at most two
dense matrix exponentials.  It requires all 69,728 coordinates to agree and a
canonical dump/fresh-load/dump byte roundtrip.

The inherited canonical serializer is **not** sufficient for this first-step
full-state target: its packet schema stores `alpha` and `operator` bytes but no
`output` bytes. Warm-1 contains 264 output coordinates (eight scalar outputs
plus the new 256-vector), all of which are part of the 67,128 packet-coordinate
denominator and are required for later continuation. A future separately
frozen serializer revision must retain those coordinates and prove both byte
and full coordinate-row roundtrips before any numerical admission can exist.

The existing corrected sparse source, stdlib oracle adapter and insufficient
serializer are inherited only as pinned inputs to future implementation
review. The N128 first-step lineage is structural precedent only; none of its
numerical qualification is transferred to N256.

Draft #6295 remains authoritative for the full N256 roster: 18,225,028
coordinates, a 27,553,312-byte largest capsule and a 291,600,448-byte
candidate-plus-dense-oracle lower bound.  This bounded first-step contract does
not amend that RED, qualify the full roster, admit later times or cold recovery,
or grant N512, arbitrary histories, second-cycle feedback, migration,
full-prior/full-network differentiation, equal-budget benefit, asynchronous
complete cost, C2 full replay, HPCA external custody, production adoption or
`all_closed`.  All historical RED and `UNKNOWN` results remain unchanged.
