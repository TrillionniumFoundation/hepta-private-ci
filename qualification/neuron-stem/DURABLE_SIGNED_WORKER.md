# Durable Signed Shared Stem Worker — Shadow Integration

This branch stacks on PR #1517 and remains **Draft, fail closed, no model
promotion or production final-use approval**. It composes the existing
`codex-hepta-infer-core::durable_control::DurableInferenceControl`, rather
than inventing a separate WAL, signature issuer or Cell lifecycle owner.

## Exactly which operations execute

1. The existing inference-control owner receives an externally authorized
   `InferenceRequest` and persists **Submit** then **Reserve** under its
   OS-locked journal. The frozen request semantic digest MUST equal the SHA-256
   of the exact serialized final-use binding, including Scope/Principal,
   frozen Stem/Head identity, ResourceGrant, request/lease/reservation and Q24
   payload. A digest is a binding, **never** an authentication of its origin.
2. `InferenceWorker::dispatch_verified_stem_durable_v1` checks that the
   **same** journal record is currently Reserved, its revision matches,
   request, principal, model, payload, token ceiling, deadline and reservation
   epoch/identity/budget are unchanged. It independently recalculates the
   full `FinalUseBinding` and compares it to the previously persisted
   `semantic_digest`.
3. The method appends an **Assign** event through the existing
   `DurableInferenceControl`, which writes, flushes and `fsync`s its
   journal. A failed/uncertain append stops before Final-use or Worker entry.
   No externally provided read-only receipt can masquerade as this write.
4. Only **after** the durable Assign does the method enter the existing
   independent, non-cloneable `VerifiedUseToken` through the host-pinned
   `FinalUseAuthority::with_verified_effect` and dispatch the actual
   loaded Head driver. There is no unsigned public Stem dispatch method.
5. The verified Worker receipt is converted into the existing
   `TerminalObservation`: actual Success/Failed/Cancelled only on observed
   terminality; without terminal evidence or on any Worker/token error,
   record **Indeterminate** with no output digest. This outcome is then
   durably settled using the same journal owner. The output digest and
   observation digest bind the real Worker response; they are not signed
   Cell checkpoint CAS receipts.
6. A crash between Assign and Settle reopens at **Assigned**; a crash after
   Settle reopens at the recorded terminal state. The dispatch function
   categorically rejects a pre-existing Assigned, Indeterminate or Completed
   record, even if the caller provides a new valid token. Only the
   independent reconciliation owner may address an uncertain effect.

## Real fixture tests and what they do NOT establish

The native tests use a real temporary file, OS writer lock, append+flush+fsync
and reopen, plus the existing ephemeral Ed25519 test-only issuer. They check
successful persisted Worker terminal, no replay after reopening, mismatched
semantic digest rejection before assignment/physical effect, and revocation
after claim causing Indeterminate persisted without claimed success.

This is **not** an independently provisioned signed Stem artifact-load receipt.
The `StemAccessContextV1` is still a caller claim. The method does not run a
genuine pretrained Jina forward, commit a Cell State Checkpoint CAS,
authenticate NDU outcomes, certify 4096 active Cells or prove unclean-crash
reconciliation/physical replay repair. The incremental 0-token Head-tick
accounting is not a measured resource cost for the external shared Encoder.

No adoption or release is allowed until the exact SHA has Rust unit tests,
fmt, strict Clippy, full App Server E2E, architecture convergence and the
global cargo-deny/Windows blocking gate **all green**, followed by physical
target-host and independent final-use/Artifact CAS evidence.
