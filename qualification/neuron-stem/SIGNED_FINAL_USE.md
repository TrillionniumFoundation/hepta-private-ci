# Shared Stem Final-use Effect Entry — Draft Contract

**Status: shadow-only contract, no production activation.** This is a stacked
follow-up to [PR #1510](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1510)
and the Jina v5 shadow qualification. It adds no model weights, no signing key,
no privileged production execution command and no unchecked grant fallback.

## What actually changes

The previously exposed
`InferenceWorker::run_bound_stem_feature_receipt_v1` now has crate-only
visibility. Product callers must use
`run_verified_stem_feature_receipt_v1(trusted_authority, verified_use,
now_ms, VerifiedStemFeatureDispatchV1)`.

The caller is required to supply an already-claimed **non-cloneable**
`codex_hepta_contracts::VerifiedUseToken`, validated by a separately owned,
trusted `FinalUseAuthority`. The Worker itself has no private signing key.
`FinalUseAuthority::with_verified_effect` rejects tokens originating from a
*different verifier instance* using `Arc::ptr_eq`, checks the exact signed
binding, current revocation/expiry state and holds the effect fence until
the bounded synchronous Worker Driver returns. The token cannot be reused.

**Critical trust caveat:** This method's `trusted_authority` argument is
a **host trust dependency**, not authenticated merely by its Rust type. An
untrusted plugin could construct its own authority if the owner let it choose
the argument. Only protected startup composition and a pinned independent
issuer, protected state/frontier, clock and revocation feed can make this a
production authentication boundary. Those product integrations are **not
claimed here**. The legacy generic `run_neuron_features` path remains
subject to its separate inference-control authority owner.

The signer signs `FinalUseBinding` with:

- `subject_id`: exact authenticated Principal StableId **claim**
- `destination_id`: `neuron.head:<selected Head StableId>`
- `scope_sha256`: complete Scope/Principal/Stem generation/authority epoch/
  lease expiry/artifact/feature digest (existing `StemFeatureRefV1` binding)
- `payload_sha256`: exact native Worker `canonical_neuron_feature_payload_digest`
- `request_sha256`: `hepta.infer-worker.stem-final-use-request.v1`
  domain hash of the request ID, reservation ID, exact model/payload/lease/
  reservation-model digests, current Worker grant ID and semantic digest,
  token/reservation ceilings, deadline, grant epoch/generation/expiry,
  cancellation bit and scoped feature reference digest

The Worker computes this binding once for an **unsigned proposal** using
`expected_stem_final_use_binding_v1`; no effect occurs. The independent owner
must approve, sign, verify and claim the *same exact binding*. Immediately
before synchronous Driver execution, the Worker recomputes it using actual
current grant and loaded Head, checks the claimed authority epoch, enters
`with_verified_effect` and invokes the internal Worker path. The result
contains a descriptive `final_use_binding_digest` but still grants
`DENY_ALL`; no signed output or NDU authorization is synthesized.

## Negative evidence/CI

Native tests use **ephemeral test-only Ed25519 keys** and a privately protected
temporary final-use directory. They verify accepted single-use entry,
nonce replay denial, a request mutated after signing, a token claimed by a
different verifier instance and revocation between claim and effect.

Exact-source Rust requirements:

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --lib
cargo +1.95.0 clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
```

The native Worker bridge CI additionally builds a real same-source App Server
binary for its Agentd integration test. Do not claim CI green before the final
exact merged SHA returns **actual** results.

## Remaining production work

An independent authority host still has to pin/rotate the issuer key, protect
the source Stem Artifact CAS, verify actual load/weight/tokenizer/projection
receipts, pin scope/grant/Generation Fence, persist the final-use token claim
and action ledger, and reconcile lost ACK or unclean crash after effect entry.
An actual fixed-weight Jina forward and real Cell Head training/4096 Cell
target-machine measurements are also still mandatory. This PR alone does not
prove production authority or NDU improvement.
