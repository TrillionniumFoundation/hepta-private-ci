# platform.wire technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `platform.wire`

**Owner:** `kernel-contracts`

**Deputy:** `integration`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7E-DEPENDENCY-INVERSION`

This stable document is the implementation guide for `platform.wire`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 0. Current implementation status

This table is the shortest authoritative distinction between executable code and
target/production work. The detailed current contract is
[`CURRENT_IMPLEMENTATION.md`](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md).

| Capability | Current state | Native source / evidence |
|---|---|---|
| Frozen HPTA V1 codec | implemented | `envelope.rs`, V1 frozen vector |
| HPTA V2 metadata+payload complete-frame digest | implemented | `integrity.rs`, V2 frozen vector |
| Explicit V1/V2 multi-version decode | implemented | `WireFrame` |
| Highest-common version negotiation with critical-feature policy | implemented | `negotiation.rs` |
| Registered schema admission + typed payload codec boundary | implemented | `schema.rs` |
| Header-first bounded stream reader | implemented | `stream.rs` |
| Deterministic property/fuzz smoke | implemented as focused tests | `protocol_tests.rs` |
| Live Rust↔Python V2 loading | qualification evidence present | `cross_language_wire_fault.rs` |
| Registered product source consumers | source-composed | `runtime.codex::adapt_wire`, `context.compiler::compile_wire` |
| Authenticated/keyed anti-tamper protection | not owned by codec | transport/authority integration required |
| Deployed production caller and target-host activation | not established | separate integration/activation gate |
| Independent acceptance/promotion/release | not granted | external governance gates |

HPTA V2's complete-frame digest is unkeyed SHA-256. It binds metadata and
payload against undetected mutation but is not a MAC, signature or source
authentication mechanism. V1 remains byte-frozen and retains its payload-only
digest semantics.

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

The registered primary compatibility anchor remains
[codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs)
with `WireEnvelope`, `WireError`, `MAX_WIRE_PAYLOAD_BYTES`, `encode` and
`decode`. The executable protocol surface now also includes:

- `integrity.rs`: `WireEnvelopeV2`, `WireFrame`, complete-frame digest;
- `negotiation.rs`: `WireOffer`, `NegotiationPolicy`, `negotiate`;
- `schema.rs`: `SchemaRegistry`, `SchemaAdmission`, `PayloadCodec`;
- `stream.rs`: header-first bounded `read_frame`.

The registered `runtime.codex` and `context.compiler` consumers now have
actual Cargo dependencies on `codex-hepta-wire` and source callsites that bind
negotiated version, producer, generation and schema before domain entry. These
are source bindings/composition, not production activation. Read the
[current executable contract](../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md)
and the
[current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation)
alongside this target architecture.

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

- `framing and codec boundary`
- `V1/V2 integrity and explicit multi-version adapter`
- `version negotiation and downgrade policy`
- `schema admission and typed payload codec boundary`
- `header-first bounded stream decoder`
- `transport-neutral error mapping`

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

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Wire framing and domain payload semantics remain separate. V1 and V2 have
independent frozen wire vectors. `SchemaRegistry` admits only registered
schemas and delegates required/unknown-field policy to the registered
`SchemaAdmission`; `PayloadCodec` supplies the matching typed encode/decode
boundary. Tests cover round trips, maximum bounds, missing required fields,
unknown fields in a strict registered schema, version downgrade rejection,
digest stability and arbitrary-byte decode smoke. Transport/domain outcome
mapping remains outside the codec.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/platform.wire.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Transport-neutral codec library, embedded by the actual transport owner.
`read_frame` validates the fixed header before allocating the variable body;
the transport still owns deadlines, cancellation and connection lifecycle.
Multi-version sessions call `negotiate` again after reconnect. Never replay an
uncertain owner effect as a codec recovery action. No standalone wire daemon or
durable domain store exists.

Current operating and state-format references:

- [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-wire/src/boundary_tests.rs](../../../codex-rs/hepta-wire/src/boundary_tests.rs): V1 truncation, bounds and independent frozen vector.
- [codex-rs/hepta-wire/src/envelope_tests.rs](../../../codex-rs/hepta-wire/src/envelope_tests.rs): V1 round trip plus explicit metadata-integrity non-claim.
- [codex-rs/hepta-wire/src/protocol_tests.rs](../../../codex-rs/hepta-wire/src/protocol_tests.rs): V2 complete-frame mutation rejection, negotiation/downgrade policy, strict schema admission, header-first streaming and deterministic fuzz/property smoke.
- [codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs](../../../codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs): live Rust↔Python V1/V2 byte boundary including a Python-generated V2 reply frame.
- [codex-rs/hepta-codex-adapter/src/wire_tests.rs](../../../codex-rs/hepta-codex-adapter/src/wire_tests.rs): registered `runtime.codex` source consumer, including downgrade/producer/generation/schema rejection.
- [codex-rs/hepta-context-compiler/src/wire_tests.rs](../../../codex-rs/hepta-context-compiler/src/wire_tests.rs): registered `context.compiler` source consumer entering the existing deterministic compiler only after the same ingress fences.

In `codex-rs`, run `just test -p codex-hepta-wire` and the focused
`codex-hepta-shadow-qualification` cross-language test. Commands are test
invocations, not stored pass receipts. Inspect the exact-candidate output for
passes, failures and skips. The
[module-specific implementation design](../../../qualification/module-execution-dossiers/detail/platform.wire.md)
separately labels production and independent-acceptance gates.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7E-DEPENDENCY-INVERSION`

The bootstrap package is `P0.7E-DEPENDENCY-INVERSION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

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
| `wireenvelope_v1` | `WireEnvelope` | `codex-rs/hepta-wire/src/envelope.rs` | `envelope_tests.rs`, `boundary_tests.rs` |
| `wireenvelope_v2` | `WireEnvelopeV2`, `WireFrame` | `codex-rs/hepta-wire/src/integrity.rs` | `protocol_tests.rs`, cross-language qualification |
| `negotiate` | `negotiate` | `codex-rs/hepta-wire/src/negotiation.rs` | `protocol_tests.rs` |
| `schema_admission` | `SchemaRegistry`, `PayloadCodec` | `codex-rs/hepta-wire/src/schema.rs` | `protocol_tests.rs` |
| `stream_decode` | `read_frame` | `codex-rs/hepta-wire/src/stream.rs` | `protocol_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- The registered `runtime.codex` and `context.compiler` consumers are source-composed; their deployment/authenticated transport state is not claimed.
- Production activation, independent acceptance, promotion and release remain false until their separate evidence gates pass.
