# platform.wire technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `platform.wire`

**Owner:** `kernel-contracts`

**Deputy:** `integration`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7E-DEPENDENCY-INVERSION`

This stable document is the implementation guide for `platform.wire`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

### Current implementation status

The table below is the current executable/source truth. Sections that describe a
broader architecture are target requirements unless this table and
[CURRENT_IMPLEMENTATION.md](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md)
bind them to native source.

| Capability | Current state | Native source/evidence |
|---|---|---|
| Frozen HPTA V1 envelope | implemented, immutable | `src/envelope.rs`, `WIRE_V1.md` |
| HPTA V2 metadata-bound frame digest | implemented | `src/envelope_v2.rs`, `WIRE_V2.md` |
| Canonical fixed-header parser | implemented | `src/frame_header.rs`; shared by one-shot and streaming decode |
| HPTN version/capability negotiation | implemented | `src/version.rs`, `NEGOTIATION_V1.md`; common advertised and selected-version effective capabilities are distinct |
| Negotiated session decode | implemented | `src/session.rs`; a live connection rejects frames outside the selected version |
| Multi-version offline frame dispatch | implemented | `src/frame.rs`; deliberately not a live-session API |
| Frozen schema/policy registry | implemented | `src/registry.rs`; bounded producer/role/capability policies and deterministic snapshot digest |
| Envelope-coupled typed payload API | implemented | `WireSession::{encode_typed_envelope,decode_typed_envelope}` prevents schema/version identity drift |
| Bounded incremental stream decoder | implemented | `src/stream.rs`; header-first admission, byte/work budgets, prefix+error batches and terminal poison state |
| Authenticated transcript and immutable session | implemented source | `src/secure_session.rs`; ordered offers, selected posture, registry snapshot and authenticated channel binding |
| Direction-separated HPTM records | implemented source | `src/directional_session.rs`; initiator/responder key derivation, independent directional sequences and reflection rejection |
| Property tests + fuzz target | implemented source evidence | `src/property_tests.rs`, `fuzz/fuzz_targets/decode_frames.rs` |
| Rust↔Python raw binary session | implemented bidirectional qualification source | `hepta-shadow-qualification/tests/cross_runtime_wire_session.rs` |
| Read-only runtime/gateway caller | source-composed | explicit V2 `Accept` on existing runtime status route |
| Product-bound runtime.codex caller | source-composed | normal `hepta-infer-worker-host` path uses HPTA V2 plus payload schema V3 before final-use claim |
| Evidence-derived lifecycle | implemented source | `scripts/platform_wire_status.py`, Lane A receipts and protected target-host workflow |
| Exact-head, merge, target-host, acceptance and release | externally evidenced | current source does not self-grant qualification, independent acceptance, activation or release |

V1 continues to use a payload-only digest. V2 binds schema, producer,
generation, lengths and payload in a domain-separated unkeyed SHA-256 digest.
Neither is an authentication primitive. `NegotiationTranscript` binds the
ordered HPTN offers, selected posture, frozen registry snapshot and an
authenticated transport channel binding. Where the transport does not already
provide equivalent directional authenticated encryption and replay ordering,
HPTM records derive disjoint initiator-to-responder and responder-to-initiator
MAC keys from the session master key and immutable session identifier. These
properties authenticate session records; they do not authorize the enclosed
domain effect or replace final-use authority checks.

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

`existing_bound` is a source-location fact: the declared target root now contains a bounded implementation and focused tests. It does not imply activation, operator acceptance, promotion or release. Source moves must update `MODULES.json`, `SOURCE_BINDINGS.json`, the Cargo/Bazel workspace and this guide in one exact candidate.

### Native source and scope

The frozen V1 source remains [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs). Current versioned source additionally includes `envelope_v2.rs`, `frame_header.rs`, `frame.rs`, `version.rs`, `session.rs`, `schema.rs`, `registry.rs`, `stream.rs`, `secure_session.rs` and `directional_session.rs`; public exports are collected in `src/lib.rs`. `FrozenSchemaRegistry` is the production policy surface, while the basic mutable `SchemaRegistry` remains a lower-level codec registry. `WireSession` couples the negotiated posture, runtime role, frozen registry snapshot and authenticated transport transcript. The public HPTM wrapper requires an explicit local initiator/responder role and derives direction-specific send/receive keys.

A named read-only caller is source-composed through `hepta-runtime` and `hepta-native-gateway`. Registered `context.compiler` and `runtime.codex` adapters enforce schema plus canonical producer admission before domain decode. The normal `hepta-infer-worker-host` runtime.codex path admits its complete App Server binding through `hepta.codex-operation-intent.v3` before the existing final-use claim and physical `turn/start`; production activation and acceptance remain separate gates. Read [CURRENT_IMPLEMENTATION.md](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md), [SECURITY_AND_QUALIFICATION.md](SECURITY_AND_QUALIFICATION.md) and the [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) alongside the target requirements in this guide.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `sql`
- `domain_runtime`
- `daemon`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `frozen HPTA framing plus one canonical fixed-header parser`
- `HPTN negotiation with common-versus-effective capability semantics`
- `selected-version session binding and envelope-coupled typed payload APIs`
- `bounded frozen schema policy with producer, role and capability admission`
- `bounded header-first decoder with byte/work ceilings and terminal poison state`
- `authenticated transcript plus direction-separated HPTM record protection`
- `transport-neutral safe error mapping and evidence-derived lifecycle status`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::platform.wire::context.compiler`
- `ModulePort::platform.wire::runtime.codex`

Consumed contracts:

- `ModulePort::platform.types::platform.wire`

Critical protocol schemas:

- HPTA frame V1 and V2;
- HPTN negotiation hello V1;
- HPTM authenticated record V1;
- `hepta.codex-operation-intent.v2` compatibility payload (unbound);
- `hepta.codex-operation-intent.v3` product payload (complete App Server binding required);
- `hepta.platform-wire.receipt.v2` qualification, acceptance and release evidence.

The V2 payload schema remains closed and is not widened in place. Payload schema
V3 still uses HPTA frame version 2; payload and framing versions are independent.
The field-level V3 contract and effect boundary are specified in
[`RUNTIME_CODEX_V3.md`](../../lane-a-foundation/platform.wire/RUNTIME_CODEX_V3.md).

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

Connection-local decode has three explicit outcomes: incomplete input, completed
frames, or a terminal error. `StreamDecodeBatch` preserves a completed prefix
when a later frame in the same chunk fails. A terminal decoder is poisoned; it
cannot accept more bytes until the old connection is discarded. Header bytes
are admitted before a declared body, and completed frames transfer ownership
rather than front-draining and shifting a shared buffer. Per-feed byte and
completed-frame work budgets bound both large-body and many-small-frame input.
Live negotiated connections use `NegotiatedStreamingDecoder`; `decode_frame`
remains an offline multi-version parser.

`WireSession` is immutable for one completed negotiation and binds the selected
version, effective capabilities, frozen registry digest, runtime role and
negotiation transcript. The public `AuthenticatedWireSession` owns independent
send and receive record state. Its local `SessionEndpoint` selects opposite
direction labels for initiator and responder, so the two peers derive matching
cross-direction keys while a reflected local outbound record or same-endpoint
peer fails MAC verification.

The [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

A protocol, resource or selected-version mismatch terminates the connection-local
decoder. The owning transport closes/quarantines that connection and negotiates
a new session; clearing a decoder does not restore trust in the same byte
stream. Valid frames completed before a later terminal error are returned in the
same batch and must not disappear because of transport chunking.

Wrong HPTM session identity, direction-derived MAC, sequence, length, format or
admitted frame is terminal. The public bidirectional authenticated session is
poisoned when either direction encounters such an error; send or receive state
is never reset in place. Recovery creates a fresh authenticated transport,
channel binding, negotiation transcript and session key.

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. HPTA V1/V2 hashes remain unkeyed integrity checks and never authenticate producer identity. Peer/session authentication requires an authenticated transport channel binding plus either transport-provided directional authenticated encryption and replay ordering or HPTM records. HPTM derives disjoint direction keys from a 32-byte master key and the immutable session identifier; transmit and receive sequence spaces are independent, and reflection is explicitly rejected.

Sensitive values are redacted or represented by digests at evidence boundaries. `SessionMacKey` rejects an all-zero key and redacts debug output; key creation, storage, rotation and destruction remain responsibilities of the transport/secret owner. Credentials, key bytes and payload bodies never enter general logs, learning datasets, prompt factors or cross-module receipts. A valid frame, transcript or MAC conveys no effect authority. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware at the downstream owner.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, downgrade, mixed-version input, metadata drift, frame/MAC tamper, replay, sequence gaps, cross-session replay, reflected records, same-endpoint direction mismatch, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation, transport equivalence or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as host qualification. Current native limits belong to [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs), `frame_header.rs`, `stream.rs`, `registry.rs` and `secure_session.rs`. `StreamingDecoder` validates the fixed header before body admission, transfers each completed frame out of its buffer and enforces both feed-byte and completed-frame work ceilings. Frozen registries cap schema entries and per-policy subjects. Authenticated records cap total record bytes before frame decode. The owning transport additionally enforces read deadlines, connection counts and selected-host resource policy; an over-budget feed or record is rejected before unbounded work or allocation.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Transport-neutral codec library, embedded by the actual transport owner. Recreate connection-local decoder, transcript and authenticated-record state after disconnect and renegotiate version; never replay an uncertain owner effect as a codec recovery action. No standalone wire daemon or durable domain store exists.

Safe diagnostics include schema/producer/role identifiers, session digest, byte offset, actual value and configured limit. They exclude payload contents, transport secrets and MAC keys. Operational status is evidence-derived rather than hand-maintained: `scripts/platform_wire_status.py` validates source-bound receipt-v2 artifacts and renders Designed/Implemented/Qualified/Accepted/Released without interpreting queued, absent, legacy or mismatched evidence as success.

Current operating and state-format references:

- [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs);
- `codex-rs/hepta-wire/src/registry.rs`;
- `codex-rs/hepta-wire/src/secure_session.rs`;
- `codex-rs/hepta-wire/src/directional_session.rs`;
- [`SECURITY_AND_QUALIFICATION.md`](SECURITY_AND_QUALIFICATION.md);
- [`STATUS.md`](STATUS.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-wire/src/boundary_tests.rs](../../../codex-rs/hepta-wire/src/boundary_tests.rs): frozen V1, truncation and bounds.
- `codex-rs/hepta-wire/src/envelope_v2_tests.rs`: frozen V2 and metadata-tamper rejection.
- `codex-rs/hepta-wire/src/version_tests.rs`: negotiation, common/effective capability separation, capability pinning and downgrade rejection.
- `codex-rs/hepta-wire/src/session_tests.rs`: negotiated frame-version binding, mixed-version rejection and valid-prefix preservation.
- `codex-rs/hepta-wire/src/schema_tests.rs`: registration, missing/unknown critical field rejection.
- `codex-rs/hepta-wire/src/registry.rs`: entry/subject ceilings, policy conflicts, producer/role/capability denial and registration-order-stable snapshot digest.
- `codex-rs/hepta-wire/src/stream_tests.rs`: chunking-invariant prefix delivery, header-first body admission, feed-byte/work ceilings, terminal poison state and buffer bounds.
- `codex-rs/hepta-wire/src/secure_session.rs`: transcript/channel binding, typed session admission, tamper, replay, sequence-gap and cross-session rejection.
- `codex-rs/hepta-wire/src/directional_session.rs`: opposite-endpoint interoperability, reflected-record rejection and same-endpoint direction mismatch.
- `codex-rs/hepta-wire/src/property_tests.rs` and `codex-rs/hepta-wire/fuzz/fuzz_targets/decode_frames.rs`: property/fuzz surfaces.
- `codex-rs/hepta-shadow-qualification/tests/cross_runtime_wire_session.rs`: bidirectional raw-binary Rust↔Python negotiation and typed V2 load, including strict duplicate-key and boolean/integer rejection.
- `codex-rs/hepta-native-gateway/src/lib.rs`: explicit content-negotiated read-only product callsite tests.
- `codex-rs/hepta-context-compiler/src/wire_tests.rs`: strict schema, payload and wrong-producer rejection.
- `codex-rs/hepta-codex-adapter/src/wire_tests.rs`: V2 compatibility rejection plus V3 complete-binding round trip, mutation and producer tests.
- `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` and the existing runtime.codex product E2E: normal product caller source and target-host test path.
- `scripts/platform_wire_status.py`: receipt-v2 validation, source consistency, distinct acceptance identities and fail-closed lifecycle derivation.
- `.github/workflows/lane-a-foundation.yml`: exact-head and deterministic synthetic-merge receipts with current test floors.
- `.github/workflows/platform-wire-target-host.yml`: exact dispatched SHA, fixed protected host profile, locked/offline target-host qualification and retained receipt.

In `codex-rs`, run `just test --locked -p codex-hepta-wire`. The exact candidate's Lane A receipt requires the current 41-test wire floor, eight registered adapter-port tests, two bidirectional cross-runtime tests and strict Clippy. Those numbers are admission floors, not stored success claims. Inspect the exact-candidate output and retained command records for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md) separately labels target acceptance designs.

Qualification is true only when source-consistent exact-head, synthetic-merge and protected target-host receipt-v2 artifacts all pass. Acceptance additionally requires distinct independent-reviewer and operations receipts, each independent of the implementation author. Release additionally requires a source-bound release receipt and artifact digest. Source code, ordinary CI and this guide cannot self-issue those external facts.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7E-DEPENDENCY-INVERSION`

The bootstrap package is `P0.7E-DEPENDENCY-INVERSION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries and focused source tests are defined. Qualification is a later evidence state requiring current exact-head, deterministic synthetic-merge and protected target-host receipts for one source SHA. Acceptance and release remain externally governed after qualification. Later planned packages may remain without invalidating documentation closure, but absent evidence never becomes an implicit pass.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. `scripts/platform_wire_status.py` then derives five monotonic, fail-closed states: Designed, Implemented, Qualified, Accepted and Released. Qualified requires current exact-head, synthetic-merge and protected target-host evidence; Accepted additionally requires distinct independent-reviewer and operations receipts; Released additionally requires a source-bound release receipt and artifact digest. Selection, activation, canary and promotion remain separate externally governed facts.

For `platform.wire`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7E-DEPENDENCY-INVERSION`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `kernel-contracts` / `integration`.
- Allowed write paths:
- `codex-rs/hepta-wire/**`
- `codex-rs/hepta-types/**`
- `codex-rs/Cargo.toml`
- Development predecessors:
- `MEM-0-TYPES`
- `P0.7B-B4-CALLSITE-PROOF`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- Activation predecessors:
- `P0.7B-B4-CALLSITE-PROOF`
- `MEM-0-TYPES`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `platform.wire` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- `ServiceGraphV1`

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-0-EXTERNAL-SYSTEM-CONTRACTS`
- `ASM-1-DISCOVERY-MANIFEST`
- `EMB-0-EMBODIED-CONTRACTS`

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `wire_v1` | `WireEnvelope` | `codex-rs/hepta-wire/src/envelope.rs` | V1 unit/boundary/frozen-vector tests |
| `wire_v2` | `WireEnvelopeV2` | `codex-rs/hepta-wire/src/envelope_v2.rs` | V2 digest/mutation/frozen-vector tests |
| `frame_header` | `FrameHeader` | `codex-rs/hepta-wire/src/frame_header.rs` | one-shot/stream parser and bound tests |
| `negotiate` | `negotiate` | `codex-rs/hepta-wire/src/version.rs` | common/effective-capability and downgrade tests |
| `session_decode` | `WireSessionDecoder` / `NegotiatedStreamingDecoder` | `codex-rs/hepta-wire/src/session.rs` | negotiated-version, mixed-version and prefix tests |
| `schema_admit` | `FrozenSchemaRegistry` / `SchemaPolicy` | `codex-rs/hepta-wire/src/registry.rs` | ceiling, snapshot, producer, role and capability tests |
| `typed_envelope` | `WireSession::{encode_typed_envelope,decode_typed_envelope}` | `codex-rs/hepta-wire/src/secure_session.rs` | envelope-coupled typed round trips and denials |
| `stream_decode` | `StreamingDecoder` | `codex-rs/hepta-wire/src/stream.rs` | header-first, byte/work budget, prefix and poison tests |
| `authenticated_session` | `WireSession` / `NegotiationTranscript` | `codex-rs/hepta-wire/src/secure_session.rs` | transcript/channel binding, replay and cross-session tests |
| `authenticated_record` | `AuthenticatedWireSession` / `SessionEndpoint` | `codex-rs/hepta-wire/src/directional_session.rs` | bidirectional, reflection and direction-mismatch tests |
| `runtime_codex_v3` | `adapt_product_wire_v3` | `codex-rs/hepta-codex-adapter/src/wire.rs` | complete-binding round-trip/mutation tests and normal worker callsite |
| `qualification_lifecycle` | `platform_wire_status.py` | `scripts/platform_wire_status.py` | receipt-v2 validation and fail-closed lifecycle self-test |

- Source identity and exact Git objects are recorded in `IMPLEMENTATION_MAP.json`; rebinding navigation evidence does not grant execution.
- The read-only runtime status path and the normal inference-worker runtime.codex V3 admission path are named source-composed callers. Registered context/compiler and runtime/Codex adapters pin canonical producer identities; these source facts are not target-host execution, deployment or operator acceptance.
- Exact-head, deterministic synthetic-merge and protected target-host execution remain separate qualification receipts. Independent reviewer and operations acceptance must be distinct external receipts, followed by a separate release receipt. Activation, canary and promotion remain outside this source map.
