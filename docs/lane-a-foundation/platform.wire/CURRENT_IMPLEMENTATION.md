# platform.wire current implementation

This document is the entry point for the **current executable** `platform.wire` contract. The broader target architecture remains in `docs/modules/platform.wire/TECHNICAL.md`; production security and evidence rules are normative in [`SECURITY_AND_QUALIFICATION.md`](../../modules/platform.wire/SECURITY_AND_QUALIFICATION.md).

## Current executable contract

| Capability | Source state | Current evidence |
| --- | --- | --- |
| Frozen HPTA V1 framing | implemented | `WIRE_V1.md`, V1 boundary tests and frozen vector |
| HPTA V2 metadata-bound digest | implemented | `WIRE_V2.md`, V2 mutation tests and frozen vector |
| HPTN version/capability negotiation | implemented | `NEGOTIATION_V1.md`; effective capabilities are restricted to the selected version |
| Session-bound decode | implemented | `WireSessionDecoder` and `NegotiatedStreamingDecoder` reject a different version before body admission |
| Multi-version offline frame dispatch | implemented | `src/frame.rs`; deliberately not a live-session API |
| Canonical fixed-header parser | implemented | `src/frame_header.rs`; shared by one-shot and streaming decode |
| Frozen schema/policy registry | implemented | bounded producer/role/capability policies and deterministic snapshot digest in `src/registry.rs` |
| Envelope-coupled typed payload API | implemented | `WireSession::{encode_typed_envelope,decode_typed_envelope}` |
| Bounded streaming decode | implemented | header-first admission, byte and frame-work budgets, valid-prefix/error batches and terminal poison state |
| Authenticated transcript/session | implemented source | ordered HPTN offers, selected posture, registry snapshot and authenticated channel binding in `src/secure_session.rs` |
| Direction-separated HPTM records | implemented source | initiator/responder key derivation, independent directional sequences and reflection rejection in `src/directional_session.rs` |
| Property testing and fuzz target | implemented source evidence | `src/property_tests.rs`, `fuzz/fuzz_targets/decode_frames.rs` |
| Bidirectional cross-runtime loading | implemented qualification source | Rust→Python and Python→Rust raw HPTN/HPTA V2 session test with strict critical-field rejection |
| Read-only runtime status caller | source-composed | explicit V2 `Accept` on the existing native-gateway runtime status route |
| Product-bound runtime.codex caller | source-composed | `hepta-infer-worker-host` admits its normal bound `turn/start` intent through HPTA V2 plus `hepta.codex-operation-intent.v3` before final-use claim |
| Exact-head / synthetic-merge evidence | workflow implemented, current receipt required | Lane A source-head and deterministic merge jobs emit schema-v2 receipts |
| Protected target-host evidence | workflow implemented, execution pending | fixed self-hosted label, protected environment and exact dispatched SHA |
| Independent acceptance / release | externally governed, absent until issued | distinct reviewer and operations receipts, then release receipt |

V1 continues to use its frozen payload-only digest. V2 binds schema, producer, generation, encoded lengths and payload into a domain-separated SHA-256 frame digest. Neither digest is a MAC or signature. Authentication begins only when an authenticated transport channel binding is included in the negotiation transcript and either the transport itself supplies equivalent directional authenticated encryption or HPTM records are used.

## Public symbols and source bindings

- V1 envelope: `src/envelope.rs` — `WireEnvelope`.
- V2 envelope: `src/envelope_v2.rs` — `WireEnvelopeV2`.
- negotiation: `src/version.rs` — `NegotiationOffer`, `WireCapabilities`, `NegotiatedWire`, `negotiate`.
- fixed header: `src/frame_header.rs` — `FrameHeader`, `ValidatedFrameHeader`.
- live negotiated decode: `src/session.rs` — `NegotiatedStreamingDecoder`, `WireSessionDecoder`.
- multi-version offline dispatch: `src/frame.rs` — `DecodedEnvelope`, `decode_frame`.
- basic schema codec boundary: `src/schema.rs` — `SchemaRegistry`, `PayloadCodec`.
- immutable production policy: `src/registry.rs` — `FrozenSchemaRegistryBuilder`, `FrozenSchemaRegistry`, `SchemaPolicy`.
- authenticated transcript and immutable session: `src/secure_session.rs` — `NegotiationTranscript`, `WireSession`.
- direction-separated public record layer: `src/directional_session.rs` — `AuthenticatedWireSession`, `SessionMacKey`, `SessionEndpoint`.
- streaming decoder: `src/stream.rs` — `StreamingDecoder`, `StreamDecodeBatch`.
- read-only caller: `codex-rs/hepta-runtime/src/lib.rs` — `HeptaRuntime::status_wire_v2`.
- read-only transport surface: `codex-rs/hepta-native-gateway/src/lib.rs`.
- registered `context.compiler` adapter: `codex-rs/hepta-context-compiler/src/wire.rs`.
- compatibility runtime.codex V2 adapter and product-bound V3 adapter: `codex-rs/hepta-codex-adapter/src/wire.rs`.
- normal product caller: `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` — `adapt_product_wire_v3` before final-use authorization and physical `turn/start`.

The existing JSON response from `GET /api/hepta/runtime` remains the default. An explicit `Accept: application/x-hepta-wire; version=2` requests the V2 representation. Unknown wire media-version requests return `406 Not Acceptable`.

The detailed product payload contract is in [`RUNTIME_CODEX_V3.md`](RUNTIME_CODEX_V3.md). The historical `hepta.codex-operation-intent.v2` payload schema remains closed and product-unbound. `hepta.codex-operation-intent.v3` requires the complete App Server binding and preserves every field used by the domain request digest. Both use HPTA frame version 2; payload schema revision is independent of frame version.

## Negotiation, session and admission invariants

`NegotiatedWire` exposes the selected version, selected-version effective capabilities, common advertised capabilities and required capabilities. Only `negotiate` constructs it. A caller cannot replace the selected version or erase requirements before passing it into a session decoder.

`WireSession` additionally binds the negotiated result to:

- one immutable `FrozenSchemaRegistry` snapshot;
- one runtime role;
- the ordered HPTN negotiation transcript;
- an authenticated transport channel binding;
- one derived session identifier.

Every admitted envelope must match the selected version, schema bounds, effective capability requirements, producer allowlist and runtime-role allowlist. Typed encode/decode uses the envelope schema and session version rather than accepting unrelated caller-supplied identities.

## Authenticated record invariants

The public `AuthenticatedWireSession` requires an explicit local endpoint role. It derives separate initiator→responder and responder→initiator keys from the master key and immutable session ID. Each direction owns a separate monotonic sequence beginning at one. A reflected outbound record or a peer configured with the same endpoint role fails MAC verification and poisons the public bidirectional session.

The HPTM record authenticates the exact HPTA bytes, session ID and sequence. It proves possession of a session key; it does not authorize the enclosed domain operation or replace the existing final-use claim and revocation checks.

A transport that already provides equivalent authenticated encryption, direction separation and replay ordering may omit HPTM only when its channel binding and equivalence are documented and independently accepted.

## Streaming and resource invariants

Connection-local decode has three explicit outcomes: incomplete input, completed frames, or a terminal error. `StreamDecodeBatch` preserves a completed prefix when a later frame in the same chunk fails. Header bytes are validated before body allocation. Per-feed byte and completed-frame budgets prevent large-body and many-small-frame abuse. Completed frames transfer ownership instead of repeatedly draining the front of a shared vector.

A terminal decoder or authenticated session is poisoned. Clearing a generic stream decoder is valid only after the old connection/session is discarded; it never restores trust in the same byte stream.

## Product composition and authority boundary

The normal inference-worker caller and read-only gateway caller are source-composed. The V3 DTO carries binding facts and digests, not `VerifiedUseToken` or another consumable grant. The existing final-use owner still revalidates and claims authority immediately before physical `turn/start`.

Successful negotiation, decode, schema admission, MAC verification, re-encode or product DTO validation is not dispatch acknowledgement, terminal external success or effect authorization.

## Evidence-derived lifecycle

`scripts/platform_wire_status.py` derives five fail-closed states:

1. `Designed` from required design documents;
2. `Implemented` from required native source files;
3. `Qualified` from source-consistent exact-head, synthetic-merge and protected target-host receipts;
4. `Accepted` from qualified state plus distinct independent-reviewer and operations receipts;
5. `Released` from accepted state plus a source-bound release receipt and artifact digest.

The Lane A workflow emits exact-head and deterministic synthetic-merge receipts even when wider Lane A work later fails. Test floors are bound to the current named suites; a zero-test filter does not qualify. The target-host workflow never checks out an input ref: it checks out `github.sha`, requires the operator-supplied expected SHA to match, uses the fixed `hepta-target-host` self-hosted label and the `platform-wire-target-host` environment, and removes temporary build products after evidence upload.

Source code cannot issue reviewer, operations or release acceptance for itself.

## Known limits and non-claims

- V1 payload integrity does not bind metadata.
- V2 metadata integrity remains unkeyed and does not authenticate a peer.
- The transport owner must provide an authenticated channel binding and protect key creation, storage, rotation and destruction.
- Additional product-domain schemas require registered strict codecs and frozen policies before admission.
- Exact-head, synthetic-merge and target-host receipts are current only for the exact SHA named in each artifact.
- Protected-environment configuration, independent review, operator acceptance, canary, promotion and release remain external governance facts.

## Verification

Current source/test identities include:

- V1/V2 unit, boundary and frozen-vector tests;
- effective-capability, downgrade and negotiation canonicality tests;
- session-bound version, producer, role and capability denial tests;
- frozen registry entry/subject limits and registration-order-stable snapshot tests;
- typed envelope round trips;
- stream chunking, valid-prefix delivery, work/byte ceilings and poison tests;
- HPTM tamper, replay, cross-session, reflected-record and same-endpoint-direction rejection;
- deterministic property tests and cargo-fuzz target;
- bidirectional raw-binary Rust↔Python HPTN/HPTA V2 tests with strict malformed-payload rejection;
- native-gateway content negotiation, `context.compiler` producer/schema checks, runtime.codex V2 compatibility and V3 complete-binding tests;
- runtime.codex product E2E through the normal inference-worker path;
- schema-v2 lifecycle receipt validation and evidence-derived status self-tests.

These are source/test identities until the exact candidate and required merge/target-host workflows pass and their artifacts are retained. Independent acceptance and release remain separate even after qualification is green.
