# platform.wire technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `platform.wire`

**Owner:** `kernel-contracts`

**Deputy:** `integration`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7E-DEPENDENCY-INVERSION`

This stable document is the implementation guide for `platform.wire`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## Current implementation status

This table is intentionally first. It separates the currently promoted executable contract from source-complete candidate work and from production/acceptance claims.

| Capability | Source state | Current executable contract | Activation / acceptance |
|---|---|---|---|
| HPTA V1 fixed envelope | implemented and frozen | **current**; `WIRE_V1.md` remains immutable | library-only; no production claim |
| HPTA V2 full-frame integrity | implemented candidate | not a reinterpretation of V1; candidate contract in `WIRE_V2.md` | exact-candidate qualification required |
| Version/capability negotiation | implemented candidate | separate from V1 decoding; unknown versions still reject | secure-session composition required |
| Schema admission + typed payload codec | implemented candidate | domain-owned schemas register explicitly | product schema owners must opt in |
| Incremental bounded decoder | implemented candidate | supports V1/V2 source candidate and admits header before body buffering | transport deadline policy remains external |
| `runtime.codex` typed source composition | implemented candidate | named source caller exists in `hepta-codex-adapter` | not deployment or external acceptance |
| Rust↔Python live process qualification | source test present | raw V2 bytes, independent digest/schema load and fault rejection | exact-head/merge-candidate receipt still required |
| Production activation | not claimed | none | **false until separate gates pass** |

The canonical Lane A truth matrix may continue to describe the promoted current contract as `fixed_v1_codec` until the candidate receives the repository's exact-head, merge-candidate and independent acceptance evidence. Source implementation and claim promotion are deliberately separate.

## 1. Identity, mission and ownership

Provide bounded, versioned wire representations while remaining transport and domain-runtime neutral.

The primary owner `kernel-contracts` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `integration` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `foundation`, kind `wire`, state model `stateless` and architecture role `contract` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-wire`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-wire`

Source implementation evidence roots:

- `codex-rs/hepta-wire`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. It does not imply activation, operator acceptance, promotion or release. Source moves must update `MODULES.json`, `SOURCE_BINDINGS.json`, the Cargo/Bazel workspace and this guide in one exact candidate.

### Native source and scope

The immutable V1 codec remains in [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs). Candidate protocol-layer sources are:

- [v2.rs](../../../codex-rs/hepta-wire/src/v2.rs) — HPTA V2 metadata+payload integrity and transport-binding digest.
- [negotiation.rs](../../../codex-rs/hepta-wire/src/negotiation.rs) — explicit version/capability negotiation and downgrade transcript digest.
- [schema.rs](../../../codex-rs/hepta-wire/src/schema.rs) — runtime schema admission and domain-owned typed payload codec boundary.
- [stream.rs](../../../codex-rs/hepta-wire/src/stream.rs) — bounded incremental frame decoder.
- [property_tests.rs](../../../codex-rs/hepta-wire/src/property_tests.rs) — deterministic property/arbitrary-byte regression coverage.

The first named product-source composition is
[codex-rs/hepta-codex-adapter/src/wire.rs](../../../codex-rs/hepta-codex-adapter/src/wire.rs). It requires negotiated HPTA V2 full-frame integrity plus schema admission before serializing or loading `CodexOperationIntent`. This is source composition evidence, not deployment authority.

Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) and the V1/V2 executable specifications together. Target architecture text never overrides the explicit status table above.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `sql`
- `domain_runtime`
- `daemon`

The framing layer validates magic, version, identity bounds, generation, lengths and digest before returning a frame. The schema layer separately admits an exact registered schema and domain-owned typed decoder. Version negotiation is a separate session concern and never makes the raw frame decoder accept unknown versions.

The module never directly writes another owner's store. It never treats serialization, decoding, schema admission, queue acceptance or handler return as authority or external effect acknowledgement.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority.

## 4. Internal architecture and component decomposition

The bounded components are:

- `V1 immutable framing and codec boundary`
- `V2 full-frame integrity codec`
- `version/capability negotiation`
- `schema registry and typed payload admission`
- `bounded incremental decoder`
- `transport-neutral error mapping`

V1 remains payload-digest compatible forever. V2 keeps a compact length-delimited layout but its embedded digest binds magic, version, lengths, generation, schema, producer and payload. The V2 digest is unkeyed and is not authentication; secure transports authenticate the complete encoded frame or the domain-separated transport-binding digest.

Negotiation selects the highest explicitly common version whose capability intersection satisfies both sides' required capabilities. Its canonical transcript digest must be authenticated by the secure session when downgrade resistance is required.

Schema registration binds an exact `StableId`, allowed wire versions, a stricter per-schema payload bound and a validator. Domain owners implement `WirePayload`; they must reject missing required fields, unknown critical fields and non-canonical values.

The incremental decoder buffers only the fixed header until all declared resource bounds pass, then buffers at most the exact single-frame body. One call completes at most one frame and returns a consumed byte count so it never turns a large input chunk into an implicit unbounded frame queue.

Configuration is immutable for one process generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::platform.wire::context.compiler`
- `ModulePort::platform.wire::runtime.codex`

Consumed contracts:

- `ModulePort::platform.types::platform.wire`

Critical protocol schemas in the canonical registry:

None.

Repository executable format references are:

- [WIRE_V1.md](../../lane-a-foundation/platform.wire/WIRE_V1.md) — immutable promoted V1 contract.
- [WIRE_V2.md](../../lane-a-foundation/platform.wire/WIRE_V2.md) — source-complete V2 candidate contract.
- `HPTA_V1_CONFORMANCE.json` and `HPTA_V2_CONFORMANCE.json` — frozen independent vectors.

Compatibility is versioned, never reinterpretive. V1 bytes and meanings cannot change in place. V2 uses version value `2`. Unknown versions reject. Required capabilities prevent silent downgrade. Unknown schemas reject before typed values are returned.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

The codec, negotiator, schema registry and decoder are process-local/stateless protocol components. No durable domain writer or migration is introduced. A product owner that persists frames remains responsible for retention, authentication context and replay semantics.

## 7. Runtime, concurrency and transaction model

No domain transaction exists inside `platform.wire`. A `WireFrameDecoder` owns only connection-local buffered bytes and an expected frame length. Disconnect, timeout or protocol error discards that state. A connection restart negotiates again.

The schema registry is explicitly constructed and passed by the caller; no process-global mutable registry is introduced.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Malformed magic/version/length/generation/identity/digest fails closed. Unknown schema, disallowed schema version, schema-specific oversize payload and typed validation failure fail closed before the typed value is returned.

Negotiation fails if either side's required capabilities cannot be satisfied. A caller requiring `FULL_FRAME_INTEGRITY` cannot fall back to V1.

Codec recovery never retries an external effect. Transport restart discards decoder state and renegotiates. Rollback may continue reading immutable V1; no release may reinterpret a V1 frame as V2.

## 9. Security, privacy and threat controls

The security boundary is explicit:

- V1 payload SHA-256 detects payload corruption only.
- V2 embedded SHA-256 detects stale/accidental mutation across metadata and payload but remains unkeyed.
- active-attacker protection requires a secure channel, MAC or signature authenticating the complete V2 frame (or `transport_binding_digest`).
- downgrade protection requires the secure session to authenticate `NegotiatedWire::transcript_digest()`.
- serialized DTOs never become permission-bearing in-process authority tokens.

Sensitive values remain outside general wire evidence unless the owning schema explicitly permits them. Security review remains mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Global payload bound remains 1,048,576 bytes; identity bounds remain 1..128 bytes. The maximum current HPTA frame is therefore bounded by the fixed header plus two maximum identities and the maximum payload.

The incremental decoder admits the 54-byte header before reserving the body and consumes at most one frame per call. Schema registrations may impose a stricter payload ceiling.

These are enforced source limits, not throughput/latency measurements. Host-specific measurements remain required before activation.

## 11. Observability and operations

`platform.wire` remains a transport-neutral library. The transport owner decides how negotiation offers are exchanged, how transcript/frame authentication is carried, and what incomplete-frame deadline applies.

Current operating and state-format references:

- [envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs)
- [v2.rs](../../../codex-rs/hepta-wire/src/v2.rs)
- [negotiation.rs](../../../codex-rs/hepta-wire/src/negotiation.rs)
- [schema.rs](../../../codex-rs/hepta-wire/src/schema.rs)
- [stream.rs](../../../codex-rs/hepta-wire/src/stream.rs)

No standalone wire daemon or durable domain store exists.

## 12. Verification and qualification

Current focused source tests include:

- V1 exact round trip, truncation sweep, bounds and frozen vector in `envelope_tests.rs` and `boundary_tests.rs`.
- V2 metadata/payload integrity mutation tests in `v2.rs`.
- highest-common negotiation and required-capability downgrade rejection in `negotiation.rs`.
- typed schema round trip, unknown schema and non-canonical payload rejection in `schema.rs`.
- incremental header admission, exact single-frame consumption and oversized advertised payload rejection in `stream.rs`.
- 512 generated V1/V2 round trips, 2,048 deterministic arbitrary-byte no-panic cases, metadata mutation checks and every chunk size 1..97 in `property_tests.rs`.
- raw Rust↔Python V2 process-pipe schema loading and metadata/payload fault rejection in `hepta-shadow-qualification/tests/cross_language_wire_fault.rs`.
- named `runtime.codex` typed source composition tests in `hepta-codex-adapter/src/wire.rs`.

In `codex-rs`, run at minimum:

- `just test -p codex-hepta-wire`
- `just test -p codex-hepta-codex-adapter`
- the focused `codex-hepta-shadow-qualification` cross-language wire test

Commands are invocations, not stored pass receipts. Exact-head and deterministic merge-candidate results remain required before claim promotion.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7E-DEPENDENCY-INVERSION`

The bootstrap package remains `P0.7E-DEPENDENCY-INVERSION`. Development, activation and evidence predecessor graphs are distinct. Contract-first source work may be complete while activation remains false.

Required deliverables remain exact source identity, source inventory, static verification, focused/package tests, all-target check, strict lint, clean worktree, exact-head execution and merge-candidate execution. Stop conditions remain authority violation, base drift, claim/evidence mismatch, cross-owner write and unbounded resource/retry behavior.

## 14. Activation, compatibility and retirement

V1 remains readable and immutable. V2 activation requires named callers to negotiate required capabilities, authenticate the negotiation transcript, use registered schemas and authenticate complete frames at the selected secure transport.

The `runtime.codex` adapter is a named **source composition**. It does not by itself establish deployed production use. Shadow/qualification callers likewise do not grant production activation.

Retirement of any older version requires all named callers migrated, no old-path use, contract parity where required, rehearsed rollback and independent acceptance.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For the V2 candidate, source implementation now covers full-frame integrity, explicit negotiation, schema admission/typed serialization, incremental decoding, property-style robustness testing and a named product-source composition. Remaining claim-boundary work is execution evidence and externally governed activation/acceptance, not an unimplemented codec API.

For `platform.wire`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7E-DEPENDENCY-INVERSION`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `kernel-contracts` / `integration`.
- Allowed owner write paths remain `codex-rs/hepta-wire/**`, `codex-rs/hepta-types/**`, and `codex-rs/Cargo.toml`; the `runtime.codex` adapter composition is a cross-owner integration change and must be reviewed as such.
- Activation predecessors remain `P0.7B-B4-CALLSITE-PROOF` and `MEM-0-TYPES`.
- Exact-head plus merge-candidate verification remains mandatory before promotion.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `platform.wire` to primary lane `LANE-A-FOUNDATION`. Mandatory implementation-level references remain:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- `ServiceGraphV1`

Consumed readiness protocols:

- None.

This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

This receipt is navigation evidence for the candidate and does not claim deployment or external effect authority.

| Operation | Native symbol | Source path | Test evidence source |
|---|---|---|---|
| V1 codec | `WireEnvelope` | `codex-rs/hepta-wire/src/envelope.rs` | `envelope_tests.rs`, `boundary_tests.rs` |
| V2 codec | `WireEnvelopeV2` | `codex-rs/hepta-wire/src/v2.rs` | inline V2 integrity tests + frozen V2 vector |
| negotiation | `negotiate` | `codex-rs/hepta-wire/src/negotiation.rs` | negotiation downgrade tests |
| schema admission | `SchemaRegistry`, `WirePayload` | `codex-rs/hepta-wire/src/schema.rs` | typed/unknown/non-canonical tests |
| incremental decode | `WireFrameDecoder` | `codex-rs/hepta-wire/src/stream.rs` | header/body bound tests |
| property robustness | module test | `codex-rs/hepta-wire/src/property_tests.rs` | generated round trips + arbitrary bytes |
| runtime.codex composition | `encode_codex_intent_frame`, `decode_codex_intent_frame` | `codex-rs/hepta-codex-adapter/src/wire.rs` | typed product-source round trip |
| cross-runtime loading | Rust producer + Python parser | `codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs` | raw process-pipe V2 test |

- Current promoted V1 contract remains frozen until candidate claim promotion completes.
- Source composition is present; deployed product execution remains a separate gate.
- Independent acceptance, activation and release remain false until their separate evidence gates pass.
