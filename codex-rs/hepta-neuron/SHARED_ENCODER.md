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

The owner can be constructed from the existing NeuronRuntimeConfigV1 tuple
with from_runtime_config, so the Encoder digest and generation are inherited
from the runtime configuration instead of being copied into an unrelated
policy object. The CellHeadV1 path consumes the resulting shared batch and
keeps each Cell's parameters, uncertainty threshold, and action digest private.

The next integration should bind the shared batch and Cell output to the local
model runtime receipt plus calibrated/OOD evidence. That receipt path must
remain independent from the shared feature artifact so one physical Encoder
forward is reused without sharing Cell state, private replay, or optimizer
state.

`MultimodalStemProjectionV1` is the deterministic input seam for the same
owner: modality-specific Q24 projectors emit one ordered vector plus an
explicit missing-modality mask, and source, manifest, and stem digests remain
available for a future evidence version. The stem does not execute the model;
its output is simply the one input vector supplied to the shared Encoder.

### Driver result identity (P0 provenance hardening)

The driver response must echo the exact `request_id` and `generation` in addition
to `encoder_digest`, `input_digest` and the canonical feature digest. The
owner checks all five bindings **before** publishing `SharedFeatureBatchV1`.
The shared batch retains the originating request ID for downstream receipt
composition. A valid feature checksum alone cannot authorize reuse of an output
from another request or generation.

This is an identity-contract safeguard only. Echoed identifiers and hashes do
not prove that a pretrained Encoder forward occurred, identify the actual
physical backend, attest the provenance ledger, or establish production
qualification. A real external model-execution receipt remains a separate P0
requirement.
