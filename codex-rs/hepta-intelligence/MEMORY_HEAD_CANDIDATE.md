# Persisted Head → MemoryCell candidate

This composition joins the real P37 task Head artifact to the existing typed
MemoryCell next-snapshot contract. It reads actual persisted bundle bytes through
the existing `LearningArtifactOwnerService`; the output remains a read-only
candidate. It does not load tensors into a model executor or change current memory.

## Flow and bindings

1. Export the trained Head with the learning-artifacts crate's bounded exporter.
   The export preserves its original JSON manifest and NPZ tensors and binds the
   checkpoint, preprocessing, scope, training/calibration sources, code and runtime.
2. Publish through the existing artifact owner and retain the full V3 admission,
   publication acknowledgement, predecessor, current registry and withdrawal pins.
3. Construct `MemoryHeadCandidateContextV1` against the current MemoryCell manifest.
   A Head-only update retains the external adapter and graph generation. Its model
   generation must advance by one and equal the persisted artifact generation.
4. The host's replay producer and independently controlled evaluator sign
   `memory_head_candidate_signing_payload_v1`. Both signatures bind the exact
   proposal, replay/evaluation references, payload provenance and owner frontiers.
5. `prepare_memory_head_candidate_v1` freshly revalidates CURRENT, the durable
   acknowledgement and current source withdrawals, then reads the actual bytes.
   It verifies all cross-contract bindings and signer separation before returning
   a privately constructed receipt containing the verified Head and candidate.

The frozen Encoder's generation is independent of the local Head generation.
The integration fixture intentionally combines Encoder generation 1 with Head
generation 2. Scope and objective must match the host's learning-evidence trust.

## What the fixture proves

The fixture uses the exact real P37 Granite linear Head tensors, not synthetic
weights or digest-only placeholders. Test-only issuer/evaluator keys establish
the mechanics of authenticated publication and readback. Tests publish, close
and reopen the owner, verify exact tensor bytes, and compose a successor while
leaving the current MemoryCell manifest unchanged. Negative cases cover changed
Encoder, sources, replay snapshot, Head payload, evaluation reference, role,
external adapter, stale withdrawal pins and colliding signer controllers.

The artifact owner's own tests additionally cover persisted payload corruption,
source withdrawal, stale CURRENT and the wrong predecessor after a real second
publication. The existing source-withdrawal and immutable-file owners remain the
only owners; this composition introduces no duplicate database or writer.

## Evidence limits and next consumers

The P37 source frontier describes historical research training/calibration input
records. It is not a production HNMF source ledger. A production host must supply
an authenticated mapping from its replay ledger before using a research export
as a production candidate. Passing a freshly recomputed untrusted digest as a
retained pin would not establish that mapping.

Signatures authenticate the attestation and controller separation. They do not
prove scientific independence, improve task quality, or replace the existing
independent evaluation/selection gates. The evaluation reference is resolved by
the evaluator before signing; this adapter does not calculate its metrics.

The output always denies activation. A later consumer must re-read current
withdrawal/registry state; retaining a prepared receipt does not freeze time.
Runtime state checkpoint persistence, task-specific memory benchmarks and live
model execution are separate integration requirements. This code does not
reinterpret a shadow checkpoint digest as a durable state snapshot.
