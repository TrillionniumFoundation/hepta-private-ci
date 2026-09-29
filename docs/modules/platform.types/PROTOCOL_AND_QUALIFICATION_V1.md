# `platform.types` protocol and qualification contract

The typed normative catalog is `codex-rs/hepta-types/src/protocol_catalog_v2.rs`.
Qualification generates exact-candidate JSON/Markdown projections. This document
specifies current protocol boundaries, not a successful qualification receipt.

## 1. Sources of truth and precedence

Use frozen versioned native contracts and the Rust catalog, executable schemas
and strict codecs, same-candidate Git/rustdoc/execution evidence, and then module
prose, in that order. The legacy exact top-level `pub use` inventory is a narrow
ownership projection; rustdoc supplies complete API comparison. Implementation
maps provide ownership/source/test navigation. Exact Git blob/tree provenance
binds current source rather than a self-referential committed head identifier.

## 2. Prompt semantic identity and migration

`PromptDeliveryObservationV1` keeps its historical custom, domain-separated,
length-framed SHA-256 commitment. It is not HPTC and is never relabeled in place.

Prompt V2 is a distinct private-field protocol:

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

Optional reason/witness values use zero-or-one arrays. Token positions use an
empty array for absence or a nonempty strictly increasing array for presence;
`Some(empty)` is invalid. V2 now admits at most 4096 positions to fit that single
frozen HPTC container. Earlier 4097..=8192 V2 values could pass construction but
not native digest generation and are now rejected at admission. The schema,
compiled catalog, Python/Node oracles and actual Rust codec share this bound.
Previously computable V2 commitments are unchanged.

`from_v1` computes the exact historical V1 digest and carries it as a witness.
V1 retains its 8192-position bound. A V1 observation larger than V2 capacity
remains readable V1 and V2 migration rejects without truncation or mutation.
A larger HPTC representation requires its own versioned protocol.

## 3. Runtime topology commitment

The V1 candidate commitment is:

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

Each delta is independently committed over its candidate/evidence/predecessor
digests, module ID, operation and related IDs. The stored candidate digest is
derived and excluded from its own preimage. Delta/related-module sets must use
strictly increasing `StableId` order; duplicates, self references and
non-canonical order reject. Product decoding returns a validated wrapper after
native structure and digest checks. This is not selection authority.

## 4. Manifest transport and product admission

The three manifests use strict JSON transport and HPTC semantic commitments.
Member order and JSON whitespace are not identity. Native validation is necessary
but does not establish product permission. Existing admission functions bind:

- random stream: exact root-seed digest, NDU namespace, generator/version,
  episode, decision and counter span;
- external system: system/class, host identity and witness equality;
- sensor: sensor/class, hardware/adapter, calibration generation, clock domain
  and failure policy.

Private-field owner receipts remain deny-only evidence. They do not execute a
system, prove counter non-reuse, authenticate a witness's current permission, or
check calibration against a trusted current time. Those final-use responsibilities
remain with the existing product owners, not `platform.types`.

## 5. Registry-bound numeric evidence

`rescale_signal` returns pure arithmetic evidence. The historical
`rescale_signal_registered` additionally checks the supplied registry while
retaining that original pure-receipt return type. Explicit V1 registry evidence
comes from `rescale_signal_registered_receipt_v1`; it binds registry content,
not an explicit monotonic generation.

V2 adds a private `RegistrySnapshotIdentityV1 { generation, registry_digest }`
binding and commits source/target profile-definition digests, the normalization
definition, canonical conversion receipt digest and V2 admission digest.
`verify` reconstructs the complete receipt but does not prove currentness.
`verify_for_snapshot` additionally requires equality with the independently
owner-pinned generation/digest and verifies the supplied registry against it
before recomputation. An old-generation or wrong-registry receipt cannot satisfy
that pin. The owner authenticates and advances the pin separately.

V2 construction now reuses already-resolved immutable definitions and the same
checked converter without creating an unused V1 admission hash. Verification is
not cached. The ordinary NDU numeric owner currently consumes V1 registered
receipts with its configured content digest; availability of the V2 library API
must not be described as completed V2 product-owner integration.

## 6. Strict transport and resource limits

All five product codecs enforce 64 KiB raw input and depth 16. Struct decoders
reject unknown/duplicate/missing fields. i64/u64 decimal strings have 20-byte
ceilings and native range checks; nullable Prompt fields are still required.
Digest strings are bounded to 64 hexadecimal bytes.

The frozen HPTC V1 profile remains 256 KiB, 4096 items per container and depth 16.
The native buffered and incremental SHA-256 APIs share all encoding, ordering,
validation and limit logic. Digest-only operation does not materialize the whole
preimage; failed encoding never publishes a partial digest.

Bounded String/Vec owned constructors normalize capacity only above their declared
maximum, after validation. Borrowed constructors validate before copying; prior
caller allocations and allocator/RSS overhead are outside logical value bounds.

## 7. API, provenance and semantic verification

Rustdoc JSON compares the PR base and candidate public API. Numeric rustdoc IDs
are normalized to stable references; genuine removals/signature/field/variant
changes reject while additive exports are reported separately. Git provenance
binds current tracked source, schemas, owner callsites, documentation, verifiers
and workflows to exact HEAD blobs and root trees.

Existing golden vectors remain frozen. Capacity regressions cover 4096, 4097,
8192 and 8193 positions, native V1 migration and product-wire roundtrip. Schema
qualification checks compiled Prompt capacity and integer width in addition to
structural catalog parity. All five product fuzz decoders assert successful
admission implies hashability and exact semantic-preserving encode/decode.
Coverage-guided fuzz remains bounded testing, not exhaustive protocol proof.

## 8. Candidate qualification, resources and review

`source-head` and deterministic `synthetic-merge` receipts are distinct. Each
requires same-candidate truth/catalog/consumer checks, provenance, rustdoc API,
MSRV, native tests/strict lint, pinned Miri, bounded fuzz and document bundle.
Failure diagnostics do not become successful receipts. The 24 independent
consumer checks must all pass; successful empty test selections reject.

Both deep truth pipelines additionally execute the actual resource probe and
allocation gate. It covers 16 cases, 17 samples of 64 operations each, with paired
buffered/streaming hash order alternation. Every pair must reduce requested
allocation bytes without increasing calls; immutable lookups must remain
allocation-free. Raw data/report hashes are retained through the committed truth
log. Time distributions are diagnostic by default. Optional latency regression
comparison requires matched environment/harness and an explicit finite ratio.
The precise allocation and sample-average timing definitions are in
`OPTIMIZATION_CLOSURE_20260929.md`; neither mode grants target-host acceptance.

Merge acceptance separately requires an eligible formal `APPROVED` review bound
to the final current head, excluding candidate authors/committers, bots, stale or
dismissed approvals and decisive changes-requested states. No receipt or review
supplies deployment, authenticated registry publication, operator acceptance,
promotion or release authority.

## 9. Reproduction

```text
python3 scripts/platform_types_public_api.py
python3 scripts/verify_lane_a_foundation.py verify
python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
bash scripts/run_platform_types_resource_qualification.sh /tmp/platform-types-resources
python3 scripts/test_platform_types_independent_review.py
```

Changes to protocol rules, schemas, codecs, public API or candidate identity
require regenerated evidence and fresh source/merge qualification. New commits
invalidate older head-bound independent review for merge-gate purposes.
