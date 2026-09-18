# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1/V2 codecs, explicit negotiation, schema admission and bounded stream reading are source-implemented; production composition and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-wire`.
Packages: `P0.7E-DEPENDENCY-INVERSION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

The implemented framing entrypoints are `WireEnvelope::{encode,decode}` for
frozen HPTA V1 and `WireEnvelopeV2::{encode,decode}` for HPTA V2.
`WireFrame::decode` is the explicit V1/V2 adapter and rejects every unknown
version.

`negotiate(local, remote, policy) -> NegotiatedWire | NegotiationError`
selects the highest explicitly common version satisfying a minimum version and
all required critical features. Requiring
`WireFeature::CompleteFrameDigest` also requires V2, so failure rejects rather
than silently downgrading to V1.

`SchemaRegistry` plus `SchemaAdmission` owns runtime schema admission;
`PayloadCodec` binds typed encode/decode to exactly one stable schema ID.
`read_frame(Read)` admits the fixed header and resource bounds before body
allocation. None of these surfaces invent a new framing format for Codex
JSON-RPC or reinterpret unknown critical fields.

## 3. State records and transaction design

No domain state or durable writer. Connection-local decoder state consists of frame length, bytes received, schema version and deadline; it is discarded on disconnect. A connection restart negotiates again. Public DTOs are distinct from permission-bearing in-process objects; serialized witnesses cannot be cast into VerifiedUse tokens.

## 4. Deterministic algorithm and scheduling

Apply size/depth/count admission before recursively decoding. Resolve message discriminator and version, validate bounded fields, then hand a typed object to the domain owner. Keep transport errors separate from rejected domain commands and unknown external-effect outcomes. Never infer a retry-safe effect from a successful re-encode.

## 5. Capacity and performance profile

Pilot envelope <= 1 MiB subject to stricter protocol bounds; nesting <= 32; at most 1024 map fields; decoder buffer <= 2 maximum frames per connection; incomplete-frame deadline is supplied by the transport profile.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- WIRE-01: V1 every-prefix truncation rejects; the stream reader validates the
  54-byte header, identity lengths, generation and payload bound before body
  allocation.
- WIRE-02: unknown wire versions reject; negotiation rejects unsatisfied
  critical features/minimum versions; a registered strict schema test rejects
  missing required fields and unknown fields.
- WIRE-03: V1 and V2 frozen vectors are exact; deterministic property/fuzz smoke
  round-trips valid V2 frames; the live Rust↔Python test validates Rust V2 bytes,
  produces a Python V2 reply and requires Rust to load it.
- WIRE-04: serialized wire values remain data only. Schema admission/typed
  decoding does not construct a permission-bearing `VerifiedUse` token.

These are source-backed verification designs. Exact-head workflow results remain
separate execution receipts and independent acceptance remains separately
governed.

## 7. Integration, rollback and capability ceiling

Every affected producer/consumer executes a contract test against one frozen schema. Domain logic and SQL stay outside this crate. Rollback requires the preceding wire version to remain readable or a documented protocol drain; no dual semantic interpretation of one version.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

**Implemented entrypoints:** `WireEnvelope` in [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs), `WireEnvelopeV2` in [codex-rs/hepta-wire/src/integrity.rs](../../../codex-rs/hepta-wire/src/integrity.rs), `negotiate` in [codex-rs/hepta-wire/src/negotiation.rs](../../../codex-rs/hepta-wire/src/negotiation.rs), `SchemaRegistry` in [codex-rs/hepta-wire/src/schema.rs](../../../codex-rs/hepta-wire/src/schema.rs), `read_frame` in [codex-rs/hepta-wire/src/stream.rs](../../../codex-rs/hepta-wire/src/stream.rs).

- **Frozen V1:** `WireEnvelope` in
  [`codex-rs/hepta-wire/src/envelope.rs`](../../../codex-rs/hepta-wire/src/envelope.rs)
  retains the original `HPTA/1` byte layout and payload-only digest semantics.
  The explicit regression
  `v1_payload_digest_does_not_claim_metadata_integrity` prevents a future
  documentation/API claim that V1 authenticates metadata.
- **V2 complete-frame integrity:** `WireEnvelopeV2`,
  `complete_frame_digest` and `WireFrame` in
  [`integrity.rs`](../../../codex-rs/hepta-wire/src/integrity.rs) implement
  `HPTA/2`. The unkeyed SHA-256 digest covers domain separator, magic,
  version, lengths, generation, schema, producer and payload. Metadata or
  payload mutation therefore fails with `FrameDigestMismatch` unless an
  adversary recomputes the unkeyed digest.
- **Negotiation:** [`negotiation.rs`](../../../codex-rs/hepta-wire/src/negotiation.rs)
  implements highest-common V1/V2 selection with minimum-version and
  critical-feature policy. Requiring complete-frame digest cannot silently
  fall back to V1.
- **Schema admission and typed serialization:**
  [`schema.rs`](../../../codex-rs/hepta-wire/src/schema.rs) implements
  `SchemaRegistry`, pluggable `SchemaAdmission` and schema-bound
  `PayloadCodec`. The wire layer provides the admission mechanism while
  domain owners retain field semantics.
- **Streaming:** [`stream.rs`](../../../codex-rs/hepta-wire/src/stream.rs)
  reads the fixed header first, validates bounds, then allocates and reads one
  bounded frame. Transport deadlines and cancellation remain transport-owned.
- **Focused source tests:**
  [`protocol_tests.rs`](../../../codex-rs/hepta-wire/src/protocol_tests.rs)
  adds V2 mutation, downgrade, schema, stream and deterministic fuzz/property
  coverage; V1 tests remain in `envelope_tests.rs` and `boundary_tests.rs`.
- **Cross-runtime qualification:**
  [`cross_language_wire_fault.rs`](../../../codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs)
  runs a live Python process that independently validates V1/V2, returns a
  Python-generated V2 frame and requires Rust to decode it.
- **Current specifications:**
  [`CURRENT_IMPLEMENTATION.md`](../../../docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md),
  [`WIRE_V1.md`](../../../docs/lane-a-foundation/platform.wire/WIRE_V1.md),
  [`WIRE_V2.md`](../../../docs/lane-a-foundation/platform.wire/WIRE_V2.md) and
  both conformance JSON vectors.

### Remaining product/external work

The repository now contains the protocol mechanisms that were previously
target-only: explicit negotiation, multi-version dispatch, schema admission and
header-first streaming. Both registered output contracts also have concrete
source consumers: `runtime.codex::adapt_wire` and
`context.compiler::compile_wire`. The remaining claim boundary is therefore
narrower:

1. those source-composed consumers are not yet evidence of an authenticated
   deployed transport or target-host production activation;
2. the V2 digest is unkeyed and therefore not a substitute for a MAC, signature
   or authenticated transport;
3. exact-head/merge-candidate CI, independent semantic acceptance, target-host
   qualification, canary, promotion and release remain separate evidence gates.

No source document or self-test may promote those external states.

