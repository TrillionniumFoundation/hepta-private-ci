# Shared Encoder owner seam

The shared Encoder seam is intentionally placed before any Cell-specific head
or System2 policy.

One SharedEncoderOwnerV1 binds one immutable encoder artifact and generation.
For each input it invokes the concrete SharedEncoderDriver exactly once, then
returns one SharedFeatureBatchV1 containing an immutable Arc feature slice
and the accepted Cell ids. features_for_cell returns that same slice for every
Cell; it does not materialize a per-Cell feature vector.

The owner verifies:

- request encoder digest and generation;
- bounded Q24 input values and canonical input digest;
- nonempty, unique, bounded Cell ids;
- output encoder/input bindings;
- bounded output values and canonical feature digest.

The trait is an execution seam, not an execution claim. A production adapter
must perform the real Encoder forward and attest its output. A digest-only fake
must remain test-only and cannot be promoted as model evidence.

The next integration should bind this batch to the existing
NeuronRuntimeConfigV1 tuple and local model runtime receipt, then feed one
shared feature slice into independent Cell heads. The head path should remain
separate from this owner so Cell state, private replay, uncertainty, and
optimizer state are never accidentally shared.
