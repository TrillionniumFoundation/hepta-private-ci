# Shared Stem signed Final-use ↔ observed Worker receipt evidence (research V1)

**Scope: additive, shadow-only, DENY_ALL.** This proposal is stacked on the
current signed Stem Final-use branch. It adds a *content-level* correlation
between the consumed, independently verified one-use token, the claimed
monotonic revocation head, the exact scoped immutable feature reference, and
the observed terminal Worker receipt. It does **not** issue or verify an
independent signer signature, attest a real Encoder model load, write an
Artifact CAS object, authorize a Cell selection, or approve production NDU.

## Failure that this closes

The existing bound Worker output carried only
`final_use_binding_digest = SHA256(serde_json(FinalUseBinding))`. A persisted
operator report could not independently correlate it with the specific
`VerifiedUseToken` claim, its claimed revocation revision/head, and the
terminal receipt's content digest. A swapped response could still retain the
same signed binding digest with no explicit content-join evidence.

## Implemented

`StemFinalUseEntryEvidenceV1` captures **after genuine synchronous Worker
execution under `FinalUseAuthority::with_verified_effect` succeeds**:

- `claimed_authority_epoch` and `claimed_revocation_revision` from the
  non-cloneable `VerifiedUseToken`;
- `claimed_revocation_head_digest` and `verified_token_witness_digest` from
  that same pre-effect, already-claimed token;
- `final_use_binding_digest` computed from the exact expected trusted
  `FinalUseBinding` used at effect entry;
- `worker_receipt_digest` from the true typed
  `NeuronFeatureReceiptV1`, not from a user-provided prediction;
- `linked_evidence_digest` across **all of the above plus the exact full
  scoped Stem reference and Worker input digest**.

The digest is SHA-256 with the existing `Digest32::of_parts` typed ordering,
domain `hepta.infer-worker.stem-final-use-entry-evidence.v1`, followed by
two big-endian u64 epoch/revision values and the six 32-byte digests in
declared order. Any change in revocation head/revision, claimed token,
binding, terminal receipt, Source Scope/Principal/generation/lease or Worker
input breaks the content join.

The new `validate_stem_final_use_entry_evidence_v1` checks every required
nonzero field, the exact typed Worker receipt, the binding equality, recomputed
linked digest and that both returned authority postures remain `DENY_ALL`.
A bare/internal unsigned Worker execution has `None` for the evidence and
must **never** pass the validator.

## Essential limitations

The validator verifies a *digest join of in-memory claim fields*. Anyone
capable of constructing a matching fake transcript can also recompute its
hash. The only signature verification remains the trusted-host
`FinalUseAuthority::claim` plus its one-use, live
`with_verified_effect` check. A real production operator must independently
persist and verify the trust-root identities, actual signed grant and
ArtifactLoadReceipt, current generation and CAS head, trusted monotonic
clock/frontier and checkpoint ledger. The token-witness digest alone **is not
a signer certificate, immutable Artifact CAS receipt, replay recovery proof,
or independent NDU acceptance**.

Negative tests flip the Worker receipt digest, Stem Scope reference and
revocation revision, and confirm that unsignatured invocation cannot supply
this evidence. They also preserve the existing real Ed25519, nonce,
cross-authority and post-claim revocation tests.

## Exact-source acceptance

Run pinned Rust fmt, library tests and Strict Clippy in the inherited
`hepta-neuron-stem-worker-bridge.yml`; both the standalone
`signed-stem-native-contracts` Job and the full Agentd/Worker E2E must
conclude green on the **same final merged SHA**. Cargo lock/security, target
hardware, real Jina pinned weights, authenticated host composition, NDU and
unclean WAL/CAS recovery remain independent gates. Do not merge or promote
based on a passing witness-content test alone.
