# `platform.types` current technical amendment V2

This amendment corrects the current executable-state portions of
`TECHNICAL.md` without deleting its architecture, work-package, compatibility,
readiness, or historical registry projections. Where the older guide describes
all prompt commitments as HPTC, limits strict Rust transport to a smaller
surface, or treats a self-contained registry receipt as freshness evidence,
this amendment, `CURRENT_IMPLEMENTATION.md`, and
`PROTOCOL_AND_QUALIFICATION_V1.md` define the current source claim.

## 1. Normative precedence

Current protocol facts are ordered as follows:

1. frozen native protocol implementation and
   `codex-rs/hepta-types/src/protocol_catalog_v2.rs`;
2. executable schemas, strict codecs and cross-language vectors;
3. exact-candidate Git/rustdoc/qualification evidence;
4. explanatory architecture prose.

The older generated registry projection remains historical/navigation evidence.
It does not override the typed V2 catalog or exact-candidate bytes.

## 2. Versioned prompt identity

`PromptDeliveryObservationV1` retains its historical custom,
domain-separated, length-framed SHA-256 commitment. It is not HPTC and its old
bytes are never reinterpreted.

`PromptDeliveryObservationV2` is a distinct private-field contract using an
HPTC schema-2 semantic commitment. Migration may include the exact V1 digest as
an explicit witness. Producers and durable consumers must not mix V1 and V2
preimages under one identity.

## 3. Registry admission and freshness

`RegisteredNumericConversionReceiptV2` binds:

- the caller-selected registry generation and content digest;
- source and target profile-definition digests;
- normalization-definition digest;
- canonical base conversion-receipt digest;
- the derived V2 admission digest.

`verify` proves self-contained receipt integrity. It does not prove that the
embedded generation is the product owner's current generation.

A generation-sensitive owner independently pins
`RegistrySnapshotIdentityV1` and calls `verify_for_snapshot`. The verifier
first checks that supplied registry bytes match the pinned digest, then requires
exact generation/digest equality with the receipt before recomputing conversion
and admission. Old-generation and wrong-registry receipts therefore fail
closed. Authenticating, publishing and advancing the pinned snapshot remains an
external owner responsibility.

## 4. Product wire ownership

`platform.wire` owns strict Rust JSON codecs for all five executable transport
contracts:

- `PromptDeliveryObservationV2`;
- `RuntimeTopologyCandidateV1`;
- `RandomStreamManifestV1`;
- `ExternalSystemManifestV1`;
- `SensorCalibrationManifestV1`.

Before Serde deserialization, each codec enforces a 64 KiB raw-input limit and
maximum nesting depth 16. Struct decoders reject duplicate, unknown and missing
fields. Precision-sensitive i64/u64 values use canonical decimal strings with
20-byte ceilings and native range checks. Digest strings have explicit 64-byte
schema ceilings. A decoded value is reconstructed through its native validated
constructor; topology is returned only through
`ValidatedRuntimeTopologyCandidateV1` after digest recomputation.

JSON transport bytes are not semantic identity. Prompt V2, topology and all
three manifests preserve their HPTC semantic commitment through the transport
projection.

## 5. Product-owner composition

Source composition now includes:

- Codex/Agentd and Learning Ledger on the frozen Prompt V1 compatibility path;
- Runtime Supervisor validated topology admission;
- NDU registered numeric admission and owner-pinned V2 snapshot verification;
- NDU random-stream admission bound to the exact root-seed digest, namespace,
  generator/version, episode, decision and counter window;
- Runtime Supervisor external-system admission bound to system/class, host
  identity and exact authorization witness;
- Runtime Supervisor sensor admission bound to sensor/class, hardware or
  adapter, calibration generation, clock domain and failure policy.

Every owner receipt remains `NonAuthorizingPosture::DENY_ALL`. These paths prove
source-level product composition, not deployed activation.

## 6. Public API and provenance

The exact top-level `pub use` inventory is retained as a narrow ownership
projection. Complete public API compatibility is generated from rustdoc JSON,
covering modules, public types, methods, fields, variants, nested type identity
and signatures. Existing public item removal or fingerprint mutation fails;
additions are reported separately.

Exact candidate provenance binds HEAD SHA/tree, root trees and tracked blobs for
source, schemas, generated catalogs, owner callsites, documents, verifiers and
workflows. An earlier observation base cannot qualify later bytes.

## 7. Qualification and independent review

Deep qualification keeps source-head and deterministic synthetic-merge
candidates non-interchangeable. Before either candidate may run the receipt
pipeline, the compiled Rust catalog is checked against every executable schema
for the exact top-level property set, required set, discriminator and closed
nested-object posture. The schema report and hashes are retained as
same-candidate artifacts.

A deep receipt additionally requires same-candidate truth, consumer,
provenance, rustdoc, MSRV, native/clippy, pinned Miri, bounded coverage-guided
fuzz and document-bundle success. The product JSON fuzz target invokes all five
registered decoders, while the raw HPTC target remains separate. Failure
diagnostics never become qualification receipts.

Merge governance is separate. The independent-review gate accepts only a formal
approval bound to the exact current head from a repository owner, member or
collaborator who is neither the PR author nor an author or committer of any
candidate commit. Stale approvals, bots, outsiders, dismissed reviews and a
latest decisive `CHANGES_REQUESTED` state reject.

## 8. Current completion boundary

Current source implementation includes native contracts, all five strict product
codecs, named manifest owners with root-seed/host/calibration identity binding,
owner-pinned registry verification, complete API and exact provenance
generation, exact catalog/schema parity, and candidate-bound qualification
machinery.

Completion is still withheld until retained exact-head and synthetic-merge
receipts pass for the final candidate and an eligible independent approval is
bound to that exact head. Deployment, authenticated registry publication,
operator acceptance, promotion and release remain separate and false.
