# channel.matrix technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `channel.matrix`

**Owner:** `channels-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `MATRIX-1-CHANNEL-BOUNDARY`

This stable document is the implementation guide for `channel.matrix`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Translate Matrix ingress and governed sends without writing agent state or self-authorizing delivery.

In GE's CNS graph this module participates in `peripheral.sensor-bus`,
`actuator.gateway` and `social.cognition`. An authenticated Matrix message is a
scoped observation, not authority to change an Agent, invoke a tool or approve an
effect. Matrixd obtains the owning Agent's existing App Server through Agentd;
it does not create another model or execution spine. Supervisor owns the
sidecar's process lifecycle and fences, while Matrix owns its durable transport
facts. These roles remain separate from learning and shared-memory admission.

The primary owner `channels-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `daemon`, state model `stateful` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`
- `codex-rs/hepta-matrix-store`
- `codex-rs/hepta-matrix-protocol`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-matrixd/src/runtime.rs](../../../codex-rs/hepta-matrixd/src/runtime.rs); observed identifiers include `MatrixRuntime`, `MatrixRuntimeBridge`, `MatrixDispatchOutcome`, `MatrixRuntimeRecovery`, `process_event`, `recover_pending`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/channel.matrix.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/channel.matrix.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.agentd`
- `kernel.authority`
- `kernel.operations`

Authoritative write domains:

- `matrix_ingress_projection`
- `matrix_dispatch_ledger`

Explicitly denied capabilities:

- `agent_store_write`
- `self_issued_send_authority`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The component decomposition targets bounded operation:

- `bootstrap and configuration loader`
- `supervision loop`
- `durable state projection`
- `readiness and shutdown controller`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### 4.1 Executable composition and ownership

| Component | Executable responsibility | Source |
|---|---|---|
| Supervisor Matrix companion | Select the paired release, start/recover one per-Agent sidecar, and observe its generation-fenced health | `codex-rs/hepta-supervisor/src/matrix.rs` |
| Matrixd runner | Acquire the per-Agent process lock; open the owner store; connect through Agentd; compose sync, inbox recovery, event projection, control and the existing sender | `codex-rs/hepta-matrixd/src/runner.rs` |
| SDK sync composer | Verify authenticated homeserver/user/device; normalize bounded observations; commit mutations and the Hepta sync cursor through the durable owner | `codex-rs/hepta-matrix-sdk/src/sdk.rs`, `sync.rs`, `gap_fill.rs` |
| Runtime bridge | Load already durable inbox entries, create/resume room threads and dispatch/reconcile through the owning App Server | `codex-rs/hepta-matrixd/src/runtime.rs` |
| Durable owner and sender | Persist dispatch/outbox identities, claim eligible messages and send with the same Matrix transaction ID | `codex-rs/hepta-matrix-store/src/store.rs`, `codex-rs/hepta-matrix-sdk/src/outbound.rs` |
| Send observer component | Validate supplied identity/digest bindings and model terminal/indeterminate outcomes in memory | `codex-rs/hepta-matrixd/src/send_observer.rs` |

`MatrixRuntime::process_event` does not advance `/sync`: its input is an event
already in the durable inbox. The live SDK path uses `MatrixSyncComposer` and
`apply_sync_decision_v2`; the standalone `MatrixIngress::ingest` helper does not
own a sync cursor. The send observer has no runner callsite, authenticated
observation source or durable persistence. Its standalone binary exits 64 and
does not start another sender. Existing transport composition is source-visible;
the complete governed `prepare_send`/`observe_send` target is still incomplete.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::matrix_dispatch_ledgerV1`
- `DomainRead::matrix_ingress_projectionV1`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::kernel.authority::channel.matrix`
- `ModulePort::kernel.operations::channel.matrix`
- `ModulePort::runtime.agentd::channel.matrix`
- `OperationIntentV1`
- `VerifiedUseTokenWitnessV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `matrix_dispatch_ledger`
- `matrix_ingress_projection`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `cross_owner_outbox`
- `operation_ledger`
- `runtime_health_observation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

The owner database is `matrix_1.sqlite3` beneath the canonical per-Agent Matrix
root. Its checked-in migrations cover inbox/outbox, sync checkpoint, logical
replacement streams, control observations, V2 sync decisions/tombstones, exact
turn-recovery cursors and unresolved outbox outcomes. Migration 0008 scope quarantine retains
already-issued dispatch identity while excluding new work from affected views.
`matrix-sdk-0.18` holds the separate SDK state/cache and private authentication
session. Neither directory is a shared multi-Agent database. The stable Matrix
plane generation preserves cursors and transactions across replaceable Agentd
spawn generations; exact binding revisions still fence stale records.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/channel.matrix.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/channel.matrix.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/channel.matrix.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/channel.matrix.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

At startup, one complete durable sync response must precede the recovery
snapshot, room-thread resume and inbox admission. A failed sync fences that SDK
instance; rebuild it from the Hepta-owned cursor rather than trusting the SDK's
possibly advanced internal token. Successful sync iterations are spaced at
least 100 ms to bound immediate-empty-response churn. Cancellation while sync
is in progress fences both the SDK instance and ingress, returns `Cancelled`
and requires reconstruction from the Hepta cursor. Reuse the recorded room/thread, client message
identity and outbox transaction across permitted recovery. A dispatched turn is
not safe to submit again merely because its response or terminal notification
was lost. Redaction of a begun, queued, admitted or completed dispatch commits its durable tombstone and quarantines the
affected binding scope rather than blocking cursor progress or cancelling the
already-issued dispatch identity. Actionable inbox, dispatch and outbox views
exclude that scope. Existing outbox records lack input lineage, so suppression
conservatively covers unsent output for the whole room/binding/generation; other
rooms continue. An already-entered or in-flight external effect may still report
its real result. This does not interrupt the remote provider or infer its
terminal state. The quarantine is immutable and cannot self-clear; bounded
`redaction_quarantines` inspection and `ResyncRequired` with
`dispatched_redaction_quarantine` report the stopped scope.
Provider-context withdrawal and independently admitted resolution remain
explicit work. Startup skips quarantined room-thread resumes, recovery and
projection; raw dispatched records remain available for forensic identity.

Already admitted turns use the same App Server persisted-turn API. A shared
budget admits at most 16 outer pages of 100 turns per recovery pass. A compare-and-set cursor
bound to the exact inbox/thread/turn/client identity survives reopen, so older
admitted turns remain reachable on later passes. Only a matching terminal turn
with a full item view, original client ID and canonical input digest projects
final/terminal outbox
records and completes dispatch; in-progress or missing observation admits no
new turn. Completion removes the exact durable turn cursor in the same
transaction. Pending-inbox recovery uses a bounded keyset window that advances
past still-pending older rows and wraps without duplicate selection; this window
frontier is process-local and restarts at zero after reopen. These are recovery
observations, not new authority.

That outer turn/RPC budget does not bound full-item hydration. `ThreadTurnsList`
with `Full` items internally calls `paginated_turn_full_items` without a total
item or internal-page cap for each turn. Its materialized response can therefore
exceed the outer window's apparent memory budget. The five-second client RPC
timeout does not cancel server-side hydration. Bounded item pagination and a
provider-side terminal/freshness fence require an additional owner seam; the
current recovery implementation does not establish a full-history memory bound.

For local `ResolveApproval`, successful transport return proves a socket write
and returns wire `Accepted`. The exact approval/decision remains durably
`resolving` across disconnect or restart. Only the authoritative matching
`ServerRequestResolved` notification concludes that resolution; the local write
must not remove its identity or claim Core accepted the decision.

For the live sender, `OutboxState::Sent` records a homeserver send acknowledgement
with its returned event ID. The SDK explicitly disables general HTTP retries
for this send request so the durable owner controls the attempt budget. An ACK
JSON or event-ID decode failure is retryable unknown delivery, not a permanent
rejection. It does not record human reading or a separate sync
echo observation. Cancellation or transport failure after possible dispatch
does not prove the event was absent. Retry exhaustion, including reclaim after
a crash on the last allowed attempt, parks the same transaction in the durable
`matrix_outbox_unresolved` record and reports `needs_reconciliation`; no further
PUT is issued after that budget. The parked record retains `InFlight`, issued
attempt and timestamps. Bounded `unresolved_outbox` inspection exposes this
uncertainty, while only that issued attempt can settle through the existing
owner ports; coalesced aliases cannot settle another transaction identity. A
later permanent transport error cannot settle an earlier lost acknowledgement:
that history also parks as `unknown_delivery`. Authenticated reconciliation
remains required; the in-memory send
observer does not supply it to the current durable sender.

## 9. Security, privacy and threat controls

Owned threat entries:

- `matrix_self_issued_send`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

The preceding list defines required boundary coverage; it does not assert that
the live Matrix sender implements every authority target. Its current checks
bind allowed room, configuration revision and Matrix generation. It does not
consume an independently issued `VerifiedUseToken` or query the current revocation
owner immediately before send. Observer digest equality is not grant
authentication. Local control uses the host owner's Unix socket and exact
process fence; Matrix message text is not that control credential. Independent
trust provisioning and final-use authority wiring remain necessary before the
governed effect target can be claimed.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/channel.matrix.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-matrixd/src/runtime.rs](../../../codex-rs/hepta-matrixd/src/runtime.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

| Enforced source parameter | Default | Supported bound / meaning |
|---|---|---|
| Sync timeline limit | 64 | 1–256 per timeline request; the live composer rejects limited timelines; the tested gap-fill helper is not yet composed |
| Sync timeout / cadence | 30 seconds / 100 ms minimum successful iteration | Timeout 1–30 seconds; startup request observation adds five seconds; mid-sync cancellation fences the SDK/ingress |
| Durable delta coalescing | 150 ms; 16 KiB batch | 100–250 ms; batch up to 64 KiB; the complete retained text prefix remains at most 1 MiB |
| Owner `event_capacity` | 1024 | 1–65536; bounds batches and change/control/scrub work; not total stored inbox/outbox capacity |
| Inbox recovery page | 1024 | Bounded keyset/wrap progress past pending older rows; process-local window frontier; no new turn replay |
| Persisted-turn recovery | 16 outer pages × 100 turns per pass | Durable cursor up to 4096 bytes; full-item hydration has no total internal item/page cap; five-second client timeout does not stop server hydration |
| Outbox claim page | 32 | 1–256 records; eligibility is resolved before selecting the bounded page |
| Outbox lease and retry | 30 seconds; 2-second initial delay; 8 attempts | Send timeout is less than the remaining lease; retry delay caps at five minutes; attempts 1–64; exhausted ambiguity parks for reconciliation |
| Normalized event / payload bytes | 1 MiB | Checked after HTTP/SDK decoding and before owner publication; complete coalesced prefix checked; no HTTP predecode byte ceiling proved |
| V2 mutation / decision journal lifetime | 65536 records each | Fixed non-reusable sequence ceilings; no implemented rotation or archival |

The pilot per-room queue target of 2048 is not a measured or currently enforced
queue SLO. `event_capacity` is not a total durable database capacity guard.
Normalization and checkpoint publication bounds do not bound an HTTP response
before SDK decoding. Fixed V2 journal budgets are lifetime limits; exhaustion
rejects before cursor advancement, and no journal rotation exists. Predecode
transport byte admission, full-item history hydration bounds, total retained
inbox/outbox capacity and authenticated archival/compaction remain source product limits, alongside target-host
throughput, lag and storage measurement.

## 11. Observability and operations

Use the existing hepta-matrixd, MatrixDurableStore and SDK sender. Keep sync/dedupe and stable send transaction identity in their existing durable owners; send_observer is a reusable state machine, not another sender. Real homeserver, encryption/session and reconnection qualification require the selected host profile.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).
- [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../readiness/LANE_B_RUNTIME_COMPOSITION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-matrix-sdk/src/gap_fill_tests.rs](../../../codex-rs/hepta-matrix-sdk/src/gap_fill_tests.rs); named case: `empty_page_continues_and_exact_target_preserves_page_and_event_order`.
- [codex-rs/hepta-matrix-sdk/src/sync_tests.rs](../../../codex-rs/hepta-matrix-sdk/src/sync_tests.rs); named case: `v1_redaction_commits_before_replay_and_survives_reopen`.

In `codex-rs`, run `just test --locked -p codex-hepta-matrix-protocol -p codex-hepta-matrix-sdk -p codex-hepta-matrix-store -p codex-hepta-matrixd`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/channel.matrix.md) separately labels target acceptance designs.

| Native test source | Coverage |
|---|---|
| `hepta-matrixd/src/runtime/tests.rs`, `runner_startup_tests.rs` | Durable inbox dispatch/reopen and sync-before-recovery ordering |
| `hepta-matrixd/src/control_lifecycle_tests.rs` | Exact-fence lifecycle/dependency loss, shutdown cleanup and socket-write-only approval resolution retained across reopen |
| `hepta-matrix-sdk/src/sync_tests.rs`, `gap_fill_tests.rs` | Atomic sync/cursor behavior, redaction and bounded gap recovery |
| `hepta-matrix-sdk/tests/durable_transport.rs`, `tests/support/outbound_boundaries.rs` | Durable sender against deterministic transport observations; storage links, lease deadlines, cancellation and exhausted uncertainty |
| `hepta-matrix-store/tests/sync_mutation_v2.rs`, `sync_observation_v1.rs` | V2 decisions/tombstones and unchanged cursor observations across reopen |
| `hepta-matrix-store/tests/outbox_adversarial.rs`, `outbox_unresolved.rs`, `storage_paths.rs` | Prefix overflow rollback, replacement fairness, restart-safe uncertainty and database path admission |
| `hepta-matrixd/src/send_observer_tests.rs` | In-memory target identity and observation-state semantics only |

Lane B CI triggers on all four Matrix roots and runs their actual protocol,
SDK/store integration and daemon tests for both source-head and synthetic-merge
candidates. The inert observer binary is not the owner-regression test matrix.
Rollback across the new recovery, uncertainty or quarantine migrations requires
a schema-compatible paired release and state; do not delete new owner records
to make an older binary appear compatible. Supervisor's paired release and
process fence are explicit constraints, not independent authority provisioning.
The separate `real-synapse-e2e` feature and checked-in hermetic Synapse fixture
exercise paired Agents, encrypted transaction identity and restart/isolation;
ordinary default tests do not execute that fixture or establish target-host
acceptance. The fixture currently requires its declared macOS/Homebrew/Docker
tool profile; it must not silently skip or be presented as a Linux CI pass.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MATRIX-1-CHANNEL-BOUNDARY`

The bootstrap package is `MATRIX-1-CHANNEL-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `channel.matrix`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MATRIX-1-CHANNEL-BOUNDARY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `channels-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-matrix-sdk/**`
- `codex-rs/hepta-matrixd/**`
- `codex-rs/hepta-matrix-store/**`
- `codex-rs/hepta-matrix-protocol/**`
- `.github/workflows/hepta-lane-b-truth.yml`
- Development predecessors:
- `P0.7B-B3-BOUNDARIES`
- Activation predecessors:
- `P0.7B-B3-BOUNDARIES`
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

The canonical readiness overlay binds `channel.matrix` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `admit_event` | `pub async fn process_event(` | `codex-rs/hepta-matrixd/src/runtime.rs` | `codex-rs/hepta-matrixd/src/runtime/tests.rs`; SDK sync/gap-fill and store mutation tests listed above |
| `prepare_send` | `pub fn prepare_send(` | `codex-rs/hepta-matrixd/src/send_observer.rs` | `codex-rs/hepta-matrixd/src/send_observer_tests.rs` |
| `observe_send` | `pub fn observe_send(` | `codex-rs/hepta-matrixd/src/send_observer.rs` | `codex-rs/hepta-matrixd/src/send_observer_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- Live runner/SDK/store callsites are listed in Section 4.1; governed final-use authority and trusted-observer composition remain follow-up work.
- Production implementation, complete governed runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.

## 18. Adversarial audit findings and completion boundary

This table records inspectable source behavior and remaining work. Tests listed
here are regression identities, not execution or external acceptance receipts.
The three mapped operation names are navigation coverage, not three completed
governed product operations.

| Completion layer | Inspectable disposition | Limit on the claim |
|---|---|---|
| Technical development documents | Detailed guide, native dossier, profile, operation/source/test mappings and source limits are present | Exact-candidate documentation validation remains separate from runtime proof |
| Native source capability | Durable sync/store, outer-window App Server recovery, lease-bounded sender, lifecycle checks and scope quarantine exist | Final-use authority, authenticated observer/reconciler, live gap fill, full-item hydration bounds and retained-capacity admission remain incomplete |
| Actual source callsites | Supervisor → Matrixd → Agentd App Server and SDK/store sender are composed | In-memory prepare/observe target and gap-fill helper have no complete governed live composition |
| External qualification / activation | Not established by this document | Provisioned trust, real transport/restore/capacity evidence and independent acceptance remain required; production/activation/release stay false |

| Boundary | Current source disposition | Remaining acceptance requirement |
|---|---|---|
| Matrix input and Agent execution | Live SDK/store/runtime/App Server composition; one owner per durable fact | Exact-candidate tests and real enrolled transport qualification |
| Live control fence / approval resolution | Live checks and shutdown joining; socket-write `Accepted` preserves resolving identity until `ServerRequestResolved` | Target-host lifecycle, disconnect and authoritative-ack qualification |
| SDK and owner private state | Reject linked directory ancestry and linked database files before SDK/owner open | Current host credential/trust provisioning and platform filesystem qualification |
| Outbox coalescing and fairness | Check cumulative text-prefix bytes transactionally; waiting replacement roots do not consume independent-stream claim pages | Selected-host capacity and sustained-history measurement |
| Governed send authority | Current sender has room/revision/generation checks; independent final-use token and revocation consumer absent | Implement current operation/room/payload-bound authority at the existing SDK adapter |
| Send terminality | Durable `Sent` is a homeserver event-ID acknowledgement; stronger observer is separate and in memory | Durable authenticated observation/reconciliation without a new sender or transaction identity |
| Uncertain retry exhaustion | One-record claims, lease-bounded sends and elapsed-time settlement; exhausted ambiguity is parked under the same transaction without a terminal-failure inference | Authenticate the reconciler and qualify crash/reopen/lost acknowledgement on the selected transport |
| Admitted-turn restart | Recover exact terminal/final identity using at most 16 outer pages of 100 turns and durable progress; per-turn Full hydration has no total item/page cap | Add bounded item pagination and the owner terminal/freshness seam; client timeout does not cancel hydration; qualify real retention/crash behavior |
| Redaction and restore | Initial sync precedes recovery; dispatched-source redaction commits a scope quarantine while retaining issued dispatch identity | Provider-context withdrawal, authenticated quarantine resolution and backup/restore non-resurrection |
| Limited timeline | Live composer rejects without advancing the cursor; bounded gap-fill helper is tested separately | Compose bounded gap fill before accepting a limited timeline or declaring reconnect completion |
| Transport / retained capacity | Normalized events and checkpoint work are bounded; HTTP predecode and total retained inbox/outbox bounds are absent; V2 journals have fixed 65536 lifetime ceilings | Implement transport byte admission, retained-capacity policy and authenticated archival/rotation; qualify sustained history |
| Production activation | False | Independently provisioned trust, exact deployment configuration, target-host evidence and independent acceptance |

Optimization follows the existing GE owners: improve sync normalization, retained
history, outbox fairness and current-fence checks locally; hand scoped evidence
to CNS/learning owners through registered contracts. No Matrix transport result
certifies model quality, shared-memory consent, physical effects or release.
