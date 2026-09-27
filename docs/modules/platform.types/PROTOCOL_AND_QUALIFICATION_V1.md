# `platform.types` protocol and qualification contract

This document defines the current executable claim boundary. The typed
normative catalog is
`codex-rs/hepta-types/src/protocol_catalog_v2.rs`; exact-candidate JSON and
Markdown projections are generated during qualification. Target architecture
prose cannot override the versioned protocol source.

## 1. Sources of truth and precedence

The precedence order is:

1. frozen versioned native protocol implementation and Rust typed catalog;
2. executable schemas, strict codecs and shared golden vectors;
3. exact-candidate rustdoc, Git provenance and qualification receipts;
4. explanatory module prose.

The legacy public ownership projection is generated from exact top-level
`pub use` statements at
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`. Complete Rust API
compatibility is derived from rustdoc JSON, including public modules, types,
methods, fields, variants and signatures. The implementation map remains a rich
ownership/source/test projection; exact byte identity is supplied by candidate
Git blob/tree provenance rather than self-referential committed SHAs.

## 2. Prompt semantic identity and migration

`PromptDeliveryObservationV1` is frozen under its historical custom,
domain-separated length-framed SHA-256 commitment. That digest is not HPTC and
must never be reinterpreted in place.

`PromptDeliveryObservationV2` is a new protocol identity:

```text
HPTC(
  type = platform.types:prompt-delivery-observation-v2,
  schema = 2,
  compilation_id,
  delivered,
  legacy_v1_digest[],
  observed_token_positions[],
  provider_request_digest,
  rejected_reason[],
  truncation_observed
)
```

Optional values use zero-or-one canonical arrays, making presence explicit.
`from_v1` computes the exact frozen V1 digest and places it in
`legacy_v1_digest`; it does not transform or relabel the old bytes. V2 fields
are private and construction is validated.

## 3. Runtime topology commitment

The V1 candidate semantic digest is:

```text
HPTC(
  type = platform.types:runtime-topology-candidate-v1,
  schema = 1,
  baseline_generation,
  candidate_generation,
  candidate_id,
  changed,
  deltas,
  evaluation_digest,
  proposal_digest,
  rollback_predecessor_digest,
  selected_topology_digest
)
```

Each delta is independently reduced to HPTC over candidate/evidence digests,
module ID, operation, predecessor digest and related-module IDs. The stored
candidate digest is derived and excluded from its own preimage.

`deltas` and `related_module_ids` are set-valued protocol fields represented by
strictly increasing `StableId` order. Duplicate, self-referential and
non-canonical sequences reject. Product JSON decoding returns a validated
wrapper only after native shape checks and digest recomputation.

## 4. Manifest transport and product admission

The three manifest protocols use strict JSON transport and HPTC semantic
commitments. JSON bytes, member order and whitespace are not semantic evidence.
The product codec bounds raw input, rejects duplicate and unknown fields and
uses canonical decimal strings for precision-sensitive 64-bit values.

Native validation is necessary but not sufficient for product use. Current
owner boundaries additionally bind:

- random stream: NDU namespace, generator/version, episode, decision and counter
  window;
- external system: Supervisor system identity/class, host identity and exact
  authorization witness;
- sensor calibration: Supervisor sensor identity/class, hardware/adapter,
  calibration generation, clock domain and failure policy.

Owner receipts are private-field, deny-only evidence. They do not execute the
systems represented by a manifest.

## 5. Registry-bound numeric evidence

V1 proves deterministic arithmetic plus content-addressed registry admission.
It remains readable compatibility evidence but does not claim an explicit
monotonic generation.

V2 adds `RegistrySnapshotIdentityV1 { generation, registry_digest }` and binds:

- exact registry generation and digest;
- source profile definition digest;
- target profile definition digest;
- normalization definition digest;
- canonical base conversion receipt digest;
- derived V2 admission digest.

The V2 receipt fields are private. `verify` reconstructs conversion and
admission from the source signal, target schema and supplied registry and
requires complete receipt equality, but deliberately treats the generation in
the receipt as self-contained integrity evidence rather than freshness.

An owner that requires anti-rollback pins its current
`RegistrySnapshotIdentityV1` independently and calls `verify_for_snapshot`.
That verifier first proves the supplied registry bytes match the pinned digest,
then requires exact generation/digest equality with the receipt before
recomputing the full conversion. A valid receipt from an older generation or a
different registry digest therefore fails closed. Authentication, publication
and advancement of the pinned current snapshot remain product-owner
responsibilities.

## 6. Strict transport limits

`platform.wire` owns the Prompt V2 and Topology V1 product codecs. Before Serde
deserialization it enforces a 64 KiB raw-input bound and maximum nesting depth
16. Derived structs deny unknown and duplicate fields. Generation strings are
canonical base-10, at most 20 bytes and range-checked before native admission.
Missing nullable fields reject rather than silently defaulting.

Python, Node and Rust consume
`PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json` and independently recompute the HPTC
semantic commitment. Raw invalid vectors include duplicate keys, excess depth
and overlong numeric strings.

## 7. Public API, provenance and semver

Qualification generates rustdoc JSON for the PR base and candidate. The crate
root is excluded from fingerprinting so additive exports do not mutate every
existing item. Removal or signature/field/variant mutation of an existing public
item fails closed; additive items are reported separately.

Git provenance enumerates the tracked source, schema, documentation, verifier
and workflow surface. Each working file must hash to the exact HEAD blob, and
root trees plus candidate SHA/tree are written into evidence. The old
observation-base convention is not accepted as a substitute for exact blob
identity.

## 8. Qualification identities and receipts

`source-head` and deterministic `synthetic-merge` are distinct candidate
classes. Their receipts are non-interchangeable. Diagnostics are retained for
failed candidates but never promoted to successful qualification.

An authoritative receipt requires all outcomes from the same candidate job:
truth/catalog/consumer checks, provenance, rustdoc API compatibility, MSRV,
native tests and lint, pinned Miri, bounded coverage-guided fuzz, and candidate
document bundle generation.

No receipt grants deployment, production activation, independent acceptance,
promotion or release.

## 9. Reproduction

```text
python3 scripts/platform_types_public_api.py
python3 scripts/verify_lane_a_foundation.py verify
python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
```

Any protocol field, semantic type, schema, validation rule, codec, public API or
candidate identity change requires regenerated candidate evidence and both
source-head and synthetic-merge qualification.
