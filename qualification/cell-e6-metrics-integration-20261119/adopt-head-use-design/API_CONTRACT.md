# Proposed API contract — design, not installed code

All names marked **new** below are proposed. None is an existing callable API or an implementation supplied by this artifact. Source references are pinned in `SOURCE_BINDINGS.json`. Existing code, generic expiry behavior and the independent NoUpdate candidate are unchanged.

## Layer 1: cryptographic data and original Artifact facts

`SignedArtifactColdUseGrantV1` (**new**, transport data) exposes only encoded fields and canonical signing bytes. Its digest includes its signature. Deserialization cannot produce a trusted policy, a reader, a writer, a selection, a Root C receipt or a FinalUse grant.

`ArtifactColdUsePolicyV1` (**new**, policy data) has no authority merely because its hash matches itself. A product has to load it through the real Artifact authority's independently pinned provisioning context. A primitive verifier that is deliberately given a test trust only proves validity relative to that trust; the Root product must never accept an arbitrary such verifier from its peer.

Conceptual signatures:

```rust
// NEW, internal to the Artifact owner module.
fn authenticate_cold_use_grant<'policy>(
    actual: &'policy OriginalArtifactHeadPolicyContextV1,
    signed: &SignedArtifactColdUseGrantV1,
    declared_d: &ColdUseTaskDescriptorV1,
    now_unix_ms: u64,
) -> Result<AuthenticatedColdUseGrantV1<'policy>, ArtifactColdUseError>;

// NEW: owned pinned source/floor, not an open publication service.
// Product construction is closed over its original config and owner identity.
struct OriginalArtifactColdUseReaderV1 { /* private files, pins, trust, policy */ }

impl OriginalArtifactColdUseReaderV1 {
    fn with_original_artifact<R>(
        &self,
        signed: &SignedArtifactColdUseGrantV1,
        declared_d: &ColdUseTaskDescriptorV1,
        now_unix_ms: u64,
        action: impl for<'read> FnOnce(
            OriginalHistoricalArtifactForColdUseV1<'read>
        ) -> Result<R, ArtifactColdUseError>,
    ) -> Result<R, ArtifactColdUseError>;
}
```

This layer uses Artifact types and digest/data descriptions; it must not depend on the Agentd crate's Root types and create a dependency cycle. `OriginalHistoricalArtifactForColdUseV1` contains only library-local facts and a scoped borrow. It has no public constructor, `Clone`, `Deserialize`, `Send`, `into_current`, `into_writer`, raw unguarded file export or mutable registry accessor. Its marker is equivalent to `PhantomData<Rc<()>>`; output lifetime cannot be selected by the caller. `R` cannot contain a borrow minted for an arbitrary `'read`.

Historical scanning may reuse private head-chain and snapshot algorithms. The **existing** `discover_current_head_unanchored(now)` still performs its final current signer and head expiry checks. The new internal scan must not expose a caller-controlled `allow_expired` or public `historical_now` route. The dedicated historical reader independently pins the exact latest physical chain tip, full registry receipt and actual file content authorized by the new grant.

### Selection

`SignedArtifactColdUseSelectionV1` (**new**) uses a new purpose and preserves the complete old selector/artifact fields, adding `grant_digest`, `d_descriptor_digest`, `policy_digest` and `policy_generation`. A new `verify_cold_use_selection` requires the scoped historical Artifact facts and exact grant. V1 remains byte-for-byte and semantically unchanged.

`VerifiedColdUseSelectionV1<'read>` (**new**) is private and remains within the reader operation. It cannot be passed to `load_selected_candidate(..., VerifiedArtifactSelectionV1)` or converted to an ordinary `VerifiedCurrentRegistryViewV1`. Exact file/hash/canonical-model checks may be factored into a private shared utility; the public authorization types stay separate.

## Layer 2: Root proves C and joins the authorities

The Artifact grant's C fields are signed conditions. Root makes them factual using the **existing** `RootFinalizedColdHistoryV1`, `RootFinalizedColdCReadV1`, `OriginalColdNextTaskContextV1`, actual files and exact retained consumer evidence. No new JSON claims to be one of these objects.

```rust
// NEW, private under the actual Root cold-task module.
struct OriginalColdUseOperationV1<'op> {
    // Existing actual context and finalized C remain borrowed here.
    // The new Artifact/Selector checks contribute facts, not Root authority.
    // All fields private; no Clone/Deserialize/Send.
}

impl RegisteredColdNextTaskV1<'_> {
    // Only this exact registered slot, same original Root identity and writer.
    fn with_original_cold_use<R>(
        &self,
        context: &OriginalColdNextTaskContextV1<'_>,
        action: impl for<'op> FnOnce(
            &OriginalColdUseOperationV1<'op>
        ) -> std::io::Result<R>,
    ) -> std::io::Result<R>;
}
```

The Root operation first verifies its actual session and finalized C, then rederives D from original files, then enters the Artifact reader and independent Selector verification, and finally compares every policy, grant, manifest, recipient, target, operation and consumer binding. Before returning it repeats Root/C/files/Artifact/withdrawal/current-policy checks. The existing original callback design does not allow a borrowed operation across an external await.

The grant descriptor deliberately excludes the subsequent Selector and final `UpdateIntent.digest()`. The selector signs the grant digest; Root's final selection observation and intent then incorporate both. A grant must not sign a hash that recursively includes itself.

The pre-selection source/target manifest is a closed manifest of actual task/runtime/data inputs, with separate mandatory authorization-envelope roles declared. The new grant, subsequent selector and final intent contents are excluded only from this early acyclic preimage; Root's later full-input manifest binds all of them and all earlier task bytes before admission. This is not permission to strip arbitrary configuration fields, ignore extra files or treat the mandatory authorization envelopes as optional.

## Layer 3: generation publication and live use

The **existing** `GenerationArtifactOwnerV1` has `Writer` and `RootInitial`, while generic prepare/publish/recovery and `LiveGenerationCurrent::new` require a writer. A new route needs a concrete **`RootColdUse` variant**, whose constructor takes only the actual Root cold client plus its registered owner state. It cannot accept caller-provided callbacks or a `dyn allow` implementation.

- `GenerationArtifactOwnerV1::writer()` returns an error for `RootColdUse`.
- `with_initial` and all old generic update/recovery/learning entry points reject it.
- A dedicated `with_original_cold_use` callback revalidates the exact registered D grant, policy, Artifact facts and Root transaction.
- New `AgentdSelectedColdUseGenerationV1` and `PreparedAgentdColdUseGenerationV1` wrappers are purpose-specific. They may share private immutable algorithms, but cannot be converted through public `From`/`Into` to ordinary selected/writer types.
- A dedicated `prepare_agentd_generation_cold_authorized_same_model_task_v1` accepts these types and the actual Root cold client. It always checks `OwnerDrainedSameModel`, exact C model, locked existing predecessor, empty/genesis target, exact D operation and original consumer. There is no caller-provided `completion` flag to widen it.
- Its publish path retains original Root `IssueFinalUse` and durable Attempted behavior, original generation CAS and post-read. Artifact use-grant never supplies `SignedFinalUseGrant`.
- Its live owner performs the same purpose checks for every generation/current validation and refuses after expiry or withdrawal. The internal publication/selection provenance must remain distinguishable from ordinary update/learning provenance; a cold-use runtime cannot obtain a learning owner from an ordinary-update downcast.

This is an integration requirement, not a promise that adding one enum variant alone compiles or is sufficient. `PATCH_PLAN.json` explicitly includes prepare, publication, recovery, live validation and Feature ownership surfaces so none silently falls back to the generic writer route.

## Persistent signing and consumption

The actual head-signing owner is not implemented by this proposal. Its required interface is an owner service around a real configured custody adapter and a durable signature journal:

```text
reserve_exact(nonce, complete grant preimage)
  -> persist SigningAttempted under the actual authority policy
  -> invoke the real custody signer once
  -> recheck actual head authority/policy/clock/files
  -> persist the exact signature and Signed receipt
```

After an unknown signing outcome it performs no automatic redispatch. Reading a previously durable identical signature is recovery, not a new grant. A test signer is allowed only in explicit component fixtures and never installed as a production default.

Root consumer reservation is bound into the original cold operation store, its profile and witness. A grant cannot be consumed by another operation/recipient/generation. The existing durable FinalUse Attempted state remains authoritative even if a later post-check fails. Recovery returns only exact already-persisted results, without a second ObjectiveStart, new nonce, broader grant, extra FinalUse or expiry extension.

## Required compile-time and source controls

The following are proposed checks, not executed evidence: no public capability constructor; no Clone/Deserialize/Send for operation types; no cross-await borrow; no fake trust accepted by a product constructor; no generic CURRENT/writer conversion; no wrong publication flavor entering learning; closed exact callers for each new constructor; per-marker removal controls for original before/after checks; and preservation of all existing CALLERS and protected entries. Any implementation must validate these on its own exact frozen source.
