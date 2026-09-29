# `platform.types` current implementation

This is the stable module-level entrypoint for executable state. Read
`TECHNICAL.md`, `PROTOCOL_AND_QUALIFICATION_V1.md` and
`OPTIMIZATION_CLOSURE_20260929.md` together. The detailed source map remains
`docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md`.

## 1. Normative precedence

When sources disagree, use this order:

1. native Rust contracts in `codex-rs/hepta-types/src/` and typed
   `protocol_catalog_v2.rs`;
2. strict product codecs in `platform.wire`, executable schemas and
   cross-language conformance vectors;
3. same-candidate provenance, rustdoc/API, test, lint, Miri, fuzz and document
   evidence;
4. current technical prose and amendments;
5. historical architecture and generated inventory projections.

Historical prose cannot override native constructors or candidate-bound bytes.
Prompt V1 is frozen custom length-framed SHA-256, not HPTC. Prompt V2 uses HPTC
schema 2. HPTC V1 itself is unchanged.

## 2. Completion vocabulary

| State | Current source claim |
| --- | --- |
| specification defined | yes |
| native source implemented | yes, with final candidate execution still required |
| five strict product codecs implemented | yes |
| named owner admission source present | capability-specific; see Section 4 |
| exact source-head qualification | determined by retained final-head receipts |
| deterministic synthetic-merge qualification | determined separately |
| eligible independent approval | separate current-head governance gate |
| authenticated registry publication | not owned by this module |
| deployed activation, promotion and release | not claimed |

An uploaded artifact, author statement or old green run is not a current pass.
The final head and synthetic merge must each pass every required outcome.

## 3. Registry identity, immutable reuse and resource bounds

`ContractRegistryV1` computes a versioned canonical SHA-256 `Digest32` once over
validated, sorted definitions/profiles. Identity/profile lookup uses binary
search. Digest lookup uses a bounded immutable `(kind, digest, entry index)`
projection. This is not an FNV checksum, signature, mutable registry service or
freshness cache.

V2 numeric admission now reuses those already-resolved definitions and calls
the same checked pure converter directly. It no longer repeats the registry
lookups or computes an unused V1 admission digest. Both schema validations,
shape/unit/normalization equality, numeric bounds, rounding and overflow checks
remain. `verify` still recomputes the complete receipt; `verify_for_snapshot`
still compares an independently pinned generation/digest before recomputation.
No authorization, freshness, final-use or deployment result is cached.

The canonical buffered and digest-only APIs share one encoder. Only the sink
differs: `Vec<u8>` versus incremental SHA-256. Framing, ordering, resource
ceilings, validation and error behavior are shared; errors discard a partial
hash instead of publishing a prefix digest. Sorting scratch allocations remain.

Owned bounded String/Vec inputs whose capacity exceeds their declared maximum
are normalized through boxed storage after validation. Within-bound allocations
are reused. Borrowed `try_from_str`/`try_from_slice` validate before allocation;
legacy owned constructors cannot undo allocation performed by `Into<String>` or
by the caller. Capacity bounds do not mean allocator overhead or physical RSS
is bounded by the same number.

## 4. Product composition boundary

| Existing owner | Current native boundary | Responsibility not supplied by the type |
| --- | --- | --- |
| Codex/Agentd and Learning Ledger | frozen Prompt V1 compatibility | durable policy and actual execution |
| Runtime Supervisor | validated topology candidate | selection and effect-boundary authority |
| NDU numeric owner | V1 registered receipt and configured immutable registry digest | authenticated provisioning and any generation-sensitive V2 migration |
| NDU random-stream admission | manifest bound to seed, namespace, generator, episode, decision and span | actual random execution and counter consumption |
| Supervisor external-system admission | system/class, host identity and witness equality | current witness authorization and observation freshness |
| Supervisor sensor admission | sensor/class, hardware, generation, clock and failure policy | trusted-clock validity at final use |

The `RegisteredNumericConversionReceiptV2` API and its owner-pinned verifier
exist in `platform.types`; this does not prove that the ordinary NDU V1 owner
already uses V2. Earlier prose that conflated these states is superseded here.
All admission receipts remain `NonAuthorizingPosture::DENY_ALL`.

## 5. Prompt capacity and migration

Prompt V2 admits at most 4096 strictly increasing token positions, matching its
single frozen HPTC array. The old 4097..=8192 V2 acceptance interval had no
computable native semantic digest and is now rejected at construction and wire
ingress with `TokenPositionLimitExceeded`. This is an explicit acceptance
correction, not a reinterpretation of previously computable digests.

Prompt V1 retains 8192 positions and its historical commitment. `from_v1`
preserves the exact V1 witness when the value fits V2; larger V1 observations
remain V1 and migration rejects without truncation or mutation. Supporting a
larger HPTC-backed representation requires a separately versioned protocol.
Schema, compiled catalog, Python/Node capacity tests and the real Rust wire test
share the 4096 limit and frozen boundary digest.

## 6. Qualification and performance evidence

Deep qualification resolves the requested source/base once, freezes their
identities, and uses pinned Rust 1.96.0 and pinned nightly qualification tools.
It keeps schema/catalog parity, semantic capacity, provenance, full rustdoc API,
MSRV, native tests/strict lint, Miri, coverage fuzz and document bundles distinct.
The consumer matrix still runs all 24 checks; successful but empty Rust test
selections cannot qualify. Consumer logs are retained under each deep candidate.

All five product fuzz decoders now assert that successful admission implies a
computable digest and semantic-preserving encode/decode roundtrip. This remains
bounded fuzz evidence, not exhaustive equivalence proof.

The new resource probe measures 16 cases with 17 samples of 64 operations. It
records allocation/reallocation call traffic and requested bytes for canonical
hashing, registry construction/lookups and numeric conversion/pinned verification.
Paired buffered/streaming hash samples alternate order. Every paired sample must
reduce requested allocation bytes without increasing allocation calls; immutable
lookups must allocate zero bytes. Timing distributions are diagnostic by default.
An optional cross-commit latency gate requires identical environment and harness
fingerprints plus an explicit ratio; it does not prove host isolation or target
acceptance. Raw sample/report hashes are bound through the mandatory truth log.

The legacy registry benchmark and its null host threshold remain unchanged.
No measured speedup or allocation result is claimed until the real executable
runs on the exact candidate. Synthetic verifier tests are not performance data.

The Rama guard retains the exact reviewed `0.3.0-alpha.4` graph, including
support crates. No dependency, lockfile or toolchain change is part of this
optimization sequence.

## 7. Public API and remaining non-claims

The committed `pub use` inventory is a narrow ownership projection, not the
complete API. Rustdoc JSON supplies full compatibility evidence; stable
structural references avoid incidental rustdoc numeric-ID renumbering.

Remaining independent obligations include successful final-head and merge
receipts, eligible current-head review, authenticated registry publication and
rotation, full historical Prompt migration where desired, real product-owner
final-use checks, target-host measurements/soak, operator acceptance, promotion
and release. Exact status belongs to GitHub and retained receipts, not a
self-referential SHA or completion Boolean in committed prose.
