# cognitive.read technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `cognitive.read`

**Owner:** `cognitive-platform`

**Deputy:** `agent-runtime`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-READ-1-SNAPSHOT-PORT`

This stable document is the implementation guide for `cognitive.read`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Expose snapshot-bound cognitive reads without write authority.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `agent-runtime` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `port`, state model `stateless` and architecture role `contract` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-cognitive-read`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-cognitive-read`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered implementation root is `codex-rs/hepta-cognitive-read`. The product-facing entrypoint is [`read_authoritative`](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs), which binds one owner-acquired immutable cognitive snapshot to a read-specific generation vector, bounded lease, acquisition request and receipt. [`read_v2`](../../../codex-rs/hepta-cognitive-read/src/v2.rs) remains the deterministic typed projection core but is no longer re-exported from the crate root; it is an internal lower-level primitive used by the authoritative boundary. The production owner adapter is [`LaneCAuthoritativeSnapshotProvider`](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs), and the named product caller is [Agentd cognitive context](../../../codex-rs/hepta-agentd/src/cognitive_context.rs). Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) alongside this guide for the exact claim boundary.

## 3. Boundary, responsibilities and non-goals

The SQLite owner exposes `CognitiveStore::lane_c_snapshot` and constructs a
request-bound `LaneCAuthoritativeSnapshotProvider` from that single immutable
transaction cut. The provider binds the exact cognitive-owned frontiers
(memory, source, tombstone, knowledge facts and knowledge-graph generation) plus
the product purpose, consumer-profile digest and host authority epoch. It does
not invent prompt, compact, model, tokenizer, template or tool-schema
generations owned elsewhere.

Agentd is the named production caller. Its default path is now
`lane_c_snapshot -> authoritative_provider -> read_authoritative -> final
owner-cut reacquisition -> revalidate_authoritative_read`. StateControl also
binds the fleet lifecycle generation as the authority epoch and requires the
same epoch after the asynchronous read completes. Exact Lane-C revision/cut
revalidation is therefore implemented; broader scope/purpose, authority epoch,
frontier, generation-vector, lease and receipt/digest revalidation is composed
at the final cognitive-context consumption boundary. Any drift fails closed.

The adapter preserves record/citation identities, includes committed
tombstones, and admits only verified currently-valid live heads. Snapshot
generation alone does not detect validity expiry without a write, so final
revalidation includes time by reacquiring the owner cut. See
[codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
No new writer, database, cross-module wire format or effect authority is
introduced.

Direct dependencies:

- `cognitive.types`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `owner snapshot acquisition`: one SQLite transaction produces an immutable `DurableCognitiveSnapshot`.
- `authoritative provider`: a request-bound `LaneCAuthoritativeSnapshotProvider` can return only that acquired cut.
- `read-specific generation vector`: binds scope, purpose, five cognitive owner frontiers/generations, consumer profile and authority epoch.
- `typed projection`: internal `read_v2` validates selectors, kinds, ordering, deduplication, stale/missing diagnostics and byte/result caps.
- `receipt binding`: `read_authoritative` binds acquisition request, generation vector, snapshot receipt and low-level read receipt.
- `consume-time verifier`: reacquires the owner cut and validates the original lease/receipt/vector plus current owner state immediately before context return.
- `host authority fence`: Agentd StateControl verifies the same lifecycle generation before and after asynchronous I/O.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::cognitive.read::context.compiler`
- `ModulePort::cognitive.read::memory.federation`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::cognitive.read::neuron.runtime`
- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::cognitive.read::utility.ndu`

Consumed contracts:

- `ModulePort::cognitive.types::cognitive.read`

Critical protocol schemas:

None.

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

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) identifies the actual state owner and lock/transaction boundary. The cognitive-read crate owns no mutable store. The persistent owner is `hepta-memory::CognitiveStore`; `lane_c_snapshot` materializes one transaction-consistent, immutable digest-only value before the cognitive-read API is invoked. This makes moving/current-state `visible()` and `fetch()` adapter implementations impossible on the product boundary: any future backend must first materialize one immutable owner cut before it can construct an authoritative provider.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

All authority and freshness failures are fail-closed. Acquisition rejects invalid scope/purpose/epoch, stale minimum frontiers, invalid lease windows, snapshot-integrity failures and request/snapshot mismatch. Consume-time revalidation rejects an expired original lease, changed provider, changed generation vector, changed owner snapshot, authority-epoch drift or receipt/digest mismatch. Agentd maps an authoritative-read failure to unavailable rather than falling back to raw `read_v2` or an unfenced SQLite read. StateControl separately fences if the fleet lifecycle generation changes across the asynchronous operation.

The exact Lane-C cut/revision revalidation gap is closed in the production source path. Remaining recovery/qualification work is not another revision check; it is exact-candidate and target-host evidence, plus independently governed activation/release gates. A source library or fixture cannot stand in for those external receipts.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Acquire a cut through the existing SQLite owner, bind the product request with `AuthoritativeReadGenerationVectorV1`, construct the request-bound Lane-C authoritative provider, and call `read_authoritative`. The authoritative result's binding digest is the read digest passed into context planning. Immediately before returning context, reacquire/revalidate the owner cut and call `revalidate_authoritative_read`; StateControl then confirms the same host authority epoch after I/O. The original lease is intentionally short and expiry is a hard failure. No historical snapshot grants future effect authority.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs): typed exact/prefix projection, missing/stale behavior, deterministic ordering and resource caps.
- [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs): provider/request/vector/query binding, lease/deadline checks and consume-time generation/authority drift.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs): real SQLite cut acquisition, freeze/reopen/tombstone behavior and authoritative provider frontier binding.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs): named product caller plus deterministic adversarial mid-flight source-frontier advance and tombstone revocation before final consume-time revalidation.
- [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs): process-level cognitive/federation revalidation behavior.

In `codex-rs`, run the focused cognitive-read, memory and Agentd tests, then the repository's exact-head qualification workflows. A command listed here is not a stored pass receipt; inspect the exact candidate output for passes, failures and skips.

### Implementation / composition status matrix

| Invariant | Implemented | Product-wired | Adversarial source test | Qualification claim |
| --- | --- | --- | --- | --- |
| Immutable owner cut / no mixed moving view | yes | yes | yes | pending exact-candidate workflow |
| Typed bounded projection / deterministic receipt | yes | yes through authoritative wrapper | yes | pending exact-candidate workflow |
| Exact revision/cut revalidation before consume | yes | yes | yes | pending exact-candidate workflow |
| Scope + purpose binding | yes | yes | yes | pending exact-candidate workflow |
| Memory/source/tombstone/KG frontiers | yes | yes | source and tombstone mid-flight cases | pending exact-candidate workflow |
| Authority epoch pre/post I/O | yes | yes through StateControl | unit + host fence source coverage | pending exact-candidate workflow |
| Generation-vector digest + snapshot receipt | yes | yes | yes | pending exact-candidate workflow |
| Short lease/deadline enforcement | yes | yes | authoritative tests | pending exact-candidate workflow |
| Independent acceptance / canary / release | repository cannot self-certify | not claimed | not applicable | open external gate |

This matrix deliberately separates source implementation, product composition, executable test presence and exact-candidate/external qualification.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-READ-1-SNAPSHOT-PORT`

The bootstrap package is `MEM-READ-1-SNAPSHOT-PORT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

A named product caller is now present: Agentd cognitive context uses the authoritative source path. This establishes the module-level `production_implementation` source fact defined by the status model; it does not by itself assert global activation, independent acceptance, canary, promotion or release. Those remain separate gates. Shadow and qualification callers are not substitutes for the named product caller.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and executable candidate tests. Composition requires a named caller. `cognitive.read` now has all three source-side pieces: an authoritative crate boundary, a real SQLite-owner provider and the Agentd product caller. Qualification still requires current exact-candidate evidence, and acceptance, selection, promotion and release remain separately governed states.

The lower-level `read_v2` contract must not be treated as the product security envelope. It is intentionally not re-exported from the crate root. Product code consumes `read_authoritative` and performs final authoritative revalidation.

For `cognitive.read`, this document grants no writer, model-provider, tool, network, filesystem, secret, Matrix, fleet, independent-acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-READ-1-SNAPSHOT-PORT`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `agent-runtime`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-read/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-0-TYPES`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `cognitive.read` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-1-SENSOR-BUS-BODY-SCHEMA`

## 17. Source implementation receipt

The bootstrap source-location obligation for `cognitive.read` is implemented by work package `MEM-READ-1-SNAPSHOT-PORT` in:

- `codex-rs/hepta-cognitive-read`

Production composition additionally delegates owner acquisition to `codex-rs/hepta-memory/src/lane_c_snapshot.rs` and is consumed by `codex-rs/hepta-agentd/src/cognitive_context.rs` under the StateControl lifecycle fence. These delegated paths do not change the module's exclusive source ownership or create another data writer.

The exact source candidate is checked by `.github/workflows/hepta-consolidated-source.yml` and Agentd qualification workflows. Until those exact-candidate runs pass, the repository should claim product composition in source, not a passing qualification receipt. No source document grants production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
