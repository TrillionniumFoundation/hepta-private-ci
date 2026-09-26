# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1 remains frozen; V2 metadata binding, HPTN negotiation, selected-version session decode, canonical header parsing, frozen schema policy, bounded streaming, authenticated transcript binding, direction-separated HPTM records, named read-only/product callers and receipt-v2 lifecycle derivation are implemented in source. Current qualification, independent acceptance and release still depend on the external evidence listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-wire`.
Packages: `P0.7E-DEPENDENCY-INVERSION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine. The framing contract, payload-schema revision, authenticated-record revision and evidence-receipt revision are independent version spaces and may not be silently conflated.

## 2. Public operations and contract details

`decode_envelope(bytes, negotiated_version, limits) -> TypedEnvelope | DecodeError` accepts only the selected session framing and canonical payload schema. `encode_envelope(value, version) -> bytes` is the inverse on supported values. `negotiate(local_offer, remote_offer, required_capabilities) -> NegotiatedWire | Incompatible` selects the highest explicitly common locally implemented version and computes selected-version effective capabilities separately from the raw common advertisement.

Production admission additionally uses an immutable `WireSession` that binds the negotiated result, one runtime role, one frozen schema/policy snapshot and an authenticated channel-bound transcript. Typed operations couple the schema identifier and frame version to that session rather than accepting unrelated caller-supplied identities. When the selected transport does not already provide equivalent directional authenticated encryption and replay ordering, `AuthenticatedWireSession` seals/opens HPTM records under direction-derived send/receive keys and independent sequence spaces.

The module must not invent a new framing format for Codex JSON-RPC, reinterpret unknown critical fields, turn a frame/MAC into domain authority, or let an offline multi-version decoder stand in for a live negotiated session.

## 3. State records and transaction design

No domain state or durable writer. Connection-local state consists of:

- admitted header/body bytes and the current stream cursor;
- configured byte and completed-frame work budgets;
- selected wire version and effective capabilities;
- immutable frozen registry snapshot, runtime role and session/transcript identifiers;
- independent HPTM outbound and inbound sequence counters where the record layer is used;
- terminal poison state.

This state is discarded on disconnect. A connection restart authenticates a new channel binding, negotiates again and creates a fresh session/key. Completed frames preceding a later bad frame are returned together with the terminal error and are not silently lost. A terminal HPTM error poisons both directions of the public authenticated session. Public DTOs remain distinct from permission-bearing in-process objects; serialized witnesses, valid MACs and admitted producer identifiers cannot be cast into `VerifiedUse` tokens.

## 4. Deterministic algorithm and scheduling

1. Parse only the canonical fixed header and validate magic, version, identifier lengths, payload length and total frame bound.
2. Enforce the live session's selected version and effective capabilities before body admission.
3. Enforce feed-byte and completed-frame work budgets; only then admit the body.
4. Resolve the schema policy from the immutable registry snapshot and validate schema range, payload bound, producer, runtime role and required capabilities.
5. Decode through the registered strict payload codec; unknown critical fields remain codec-owned hard failures.
6. For HPTM, verify record format, immutable session identifier, expected directional sequence and direction-derived HMAC before frame use.
7. Transfer completed frame ownership without repeatedly front-draining an unread suffix.
8. Hand a typed object to the domain owner without inferring effect authorization or terminal external success.

Keep transport errors separate from rejected domain commands and unknown external-effect outcomes. Never infer a retry-safe effect from successful decoding, MAC verification or re-encoding.

## 5. Capacity and performance profile

HPTA payloads remain bounded by the frozen protocol ceiling (currently 1 MiB subject to stricter schema limits). Identifier lengths, frame bytes, frozen registry entries, per-policy subjects, per-feed bytes, completed frames per feed, pending stream bytes and authenticated-record bytes have explicit source constants. Header validation occurs before body allocation. The stream implementation bounds both large-body and many-small-frame work.

Nesting depth and map-field ceilings are properties of each registered strict payload codec; they are not silently claimed by the generic wire core. Incomplete-frame deadlines, connection counts and host-level memory/CPU ceilings are supplied by the transport/target-host profile.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind the actual schema, authenticated transport profile, selected host and retained measurements before production composition; stateless modules prove absence of durable state rather than inventing it.

## 6. Concrete verification cases

- WIRE-01: truncation at every frame boundary returns incomplete/rejected without domain invocation.
- WIRE-02: unknown critical version/field rejects; additive optional fields follow the registered compatibility policy.
- WIRE-03: maximum-size round trip and cross-language golden encodings are exact.
- WIRE-04: a serialized authority witness, admitted producer or valid MAC never constructs a consumable token.
- WIRE-05: a valid frame followed by a bad frame yields the same valid prefix and terminal error under every transport chunking.
- WIRE-06: a negotiated V2 session rejects a subsequent V1 frame and remains poisoned.
- WIRE-07: product-bound runtime.codex V3 round-trips every App Server binding field without changing the domain request digest.
- WIRE-08: frozen registry snapshots are registration-order stable, bounded and reject producer/role/capability mismatches.
- WIRE-09: frame/MAC tamper, replay, sequence gaps, cross-session replay, reflected outbound records and same-endpoint HPTM peers reject and poison the session.
- WIRE-10: exact-head, synthetic-merge, protected target-host, independent-reviewer, operations and release receipt-v2 inputs fail closed on malformed, legacy, source-inconsistent or self-attested evidence.

These are required test designs and source identities, not executed-test receipts. Each implementation supplies exact input/output, current source identity, retained command record and independent oracle evidence where applicable.

## 7. Integration, rollback and capability ceiling

Every affected producer/consumer executes a contract test against one frozen schema/policy snapshot. Domain logic and SQL stay outside this crate. Rollback requires the preceding wire version to remain readable or a documented protocol drain; no dual semantic interpretation of one framing, payload, record or receipt revision.

A transport may omit HPTM only after documenting that its authenticated channel supplies equivalent peer binding, direction separation, record integrity and replay ordering and after that equivalence is independently reviewed. The transport/secret owner controls master-key creation, storage, rotation and destruction. `platform.wire` does not persist key bytes.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective at the downstream final-use authority boundary; a frozen wire snapshot cannot override revocation. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented framing entrypoints:** `WireEnvelope` in [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs); `WireEnvelopeV2` in [codex-rs/hepta-wire/src/envelope_v2.rs](../../../codex-rs/hepta-wire/src/envelope_v2.rs); canonical `FrameHeader`/`ValidatedFrameHeader` in `src/frame_header.rs`; multi-version offline `decode_frame` in `src/frame.rs`. Offline dispatch is not a negotiated live-session API.
- **Negotiation and live decode:** `NegotiationOffer`, `WireCapabilities`, `NegotiatedWire` and `negotiate` in `src/version.rs` implement bounded HPTN V1 and separate common advertised from selected-version effective capabilities. Required capability pinning prevents silent fallback. `NegotiatedStreamingDecoder` and `WireSessionDecoder` in `src/session.rs` reject a frame whose version differs from the completed selection and preserve terminal poison semantics.
- **Frozen policy and typed admission:** `FrozenSchemaRegistryBuilder`, `FrozenSchemaRegistry` and `SchemaPolicy` in `src/registry.rs` bound schema entries and policy subjects, freeze producer/role/capability requirements and compute a deterministic snapshot digest. `WireSession::{encode_typed_envelope,decode_typed_envelope}` couples typed payloads to the admitted envelope schema and session version. The basic `SchemaRegistry`/`PayloadCodec` in `src/schema.rs` remains a lower-level codec boundary.
- **Streaming:** `StreamingDecoder` in `src/stream.rs` validates the fixed header before advertised-body admission, preserves completed-prefix plus later-error batches, transfers frame ownership without repeated front-drain shifts, enforces pending-byte and per-feed frame-work ceilings, and becomes terminally poisoned after protocol/resource failure.
- **Authenticated transcript/session:** `NegotiationTranscript` and `WireSession` in `src/secure_session.rs` bind ordered initiator/responder offers, selected posture, frozen registry snapshot and a 16–512 byte authenticated transport channel binding into one session identifier. The internal HPTM record codec binds exact HPTA bytes, session identifier and sequence and rejects tamper, replay, gaps and cross-session use.
- **Direction separation:** the public `AuthenticatedWireSession`, `SessionMacKey` and `SessionEndpoint` in `src/directional_session.rs` derive disjoint initiator→responder and responder→initiator HMAC keys from the master key plus immutable session identifier. Outbound and inbound counters are independent. Reflected local outbound records and same-endpoint peers fail MAC verification; a terminal error poisons both public directions. Key debug output is redacted and all-zero master keys reject.
- **Integrity and authority boundary:** V1 retains the historical payload-only digest. V2 computes a domain-separated unkeyed SHA-256 over magic, version, lengths, generation, schema, producer and payload. Neither digest is a MAC/signature. HPTM proves possession of a session key, not domain authority. The existing final-use owner still validates and claims permission immediately before the physical effect.
- **Source composition:** `hepta-runtime::HeptaRuntime::status_wire_v2` encodes the existing read-only status payload, and `hepta-native-gateway` returns it only when the existing runtime route receives `Accept: application/x-hepta-wire; version=2`; the default JSON representation is unchanged and unknown wire media versions return 406. `hepta-context-compiler` composes strict schema/producer admission. The compatibility runtime.codex payload V2 remains unbound; payload V3 requires every `AppServerRequestBinding` field. The normal `hepta-infer-worker-host` path calls `adapt_product_wire_v3` before the existing final-use claim and physical `turn/start`. The DTO carries binding facts and digests, not a consumable authority token.
- **Evidence lifecycle:** `scripts/platform_wire_status.py` validates `hepta.platform-wire.receipt.v2` inputs and derives Designed, Implemented, Qualified, Accepted and Released. Qualified requires source-consistent exact-head, deterministic synthetic-merge and protected target-host receipts. Accepted additionally requires distinct independent-reviewer and operations identities, each independent of the implementation author. Released additionally requires a source-bound release receipt and artifact digest. Missing, queued, malformed, legacy or inconsistent evidence does not pass.
- **Workflow safety:** Lane A emits strict exact-head and synthetic-merge receipts with current test floors. The target-host workflow checks out only `github.sha`, requires the operator-supplied expected SHA to match, uses fixed `self-hosted`/`hepta-target-host` labels plus the protected `platform-wire-target-host` environment, runs locked/offline with a per-run target directory and removes build products afterward. Arbitrary input refs and runner labels are not executed.
- **Verification sources:** V1/V2 boundary and frozen-vector tests; common/effective capability and downgrade tests; negotiated-session mixed-version tests; frozen-registry ceiling/snapshot/policy tests; stream prefix/header/work/poison tests; transcript/HPTM tamper, replay and cross-session tests; direction/reflection tests; deterministic property tests and cargo-fuzz target; bidirectional strict Rust↔Python HPTN+V2 test; gateway content-negotiation tests; runtime.codex V3 complete-binding tests; normal product E2E; receipt-v2 lifecycle self-test. These remain source/test identities until exact-candidate receipts are current.
- **Current references:** `docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md`, `docs/modules/platform.wire/SECURITY_AND_QUALIFICATION.md`, `docs/modules/platform.wire/STATUS.md`, `WIRE_V1.md`, `WIRE_V2.md`, `NEGOTIATION_V1.md`, `RUNTIME_CODEX_V3.md`, `HPTA_V1_CONFORMANCE.json`, `HPTA_V2_CONFORMANCE.json` and `HPTN_V1_CONFORMANCE.json`.
- **Remaining work/evidence:** compose the authenticated `WireSession`/transport-equivalent or HPTM posture into every selected production transport; register each additional production domain schema/codec; obtain passing exact-head, synthetic-merge and protected target-host receipts for one final source SHA; obtain distinct independent semantic/security reviewer and operations acceptance receipts; then perform activation, canary, promotion and source-bound release. Source composition and ordinary CI alone do not grant those states.
