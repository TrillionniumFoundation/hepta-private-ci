# channel.matrix: implementation design

Parent: `docs/modules/channel.matrix/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: live per-Agent SDK/store/runtime/App Server composition exists. The complete governed send-authority and independent-observer target is incomplete; remaining source capabilities and external qualification are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-matrix-sdk`, `codex-rs/hepta-matrixd`.
Packages: `MATRIX-1-CHANNEL-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_event(room, event, sync_generation, principal) -> IngressObservation`; `prepare_send(room, message_digest, operation_id, grant) -> SendIntent`; `observe_send(transaction_id, server_evidence) -> DeliveryDisposition`. Room, homeserver, authenticated user/device and encryption/session generation are explicit. Message text is untrusted evidence, not an administrative command.

## 3. State records and transaction design

`matrix_ingress_projection` keys homeserver+room+event ID and retains source digest, sync position, sender evidence, redaction/correction and scope. `matrix_dispatch_ledger` keys operation ID and Matrix transaction ID with payload, room/session generation, grant epoch and observed server event. Persist dedupe and sync-watermark advancement atomically or through a recoverable staged watermark.

## 4. Deterministic algorithm and scheduling

Validate enrolled room and session; dedupe by server event identity; apply source correction/redaction; publish bounded ingress. For sending, consume final room/payload-bound authority; preserve the same transaction identity across a permitted reconciliation; distinguish the homeserver send acknowledgement/event ID, independently observed event presence and downstream user reading. Reconnect resumes a durable watermark without replaying revoked content.

## 5. Capacity and performance profile

Pilot ingress batch <= 512 events, payload <= the registered Matrix boundary limit, per-room queue <= 2048 and reconnect attempts bounded by host policy. Report sync lag, queue age, redaction propagation and unresolved send count.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- MATRIX-01: duplicate events across reconnect append no duplicate learning/source event.
- MATRIX-02: room/session generation or payload drift is rejected before send.
- MATRIX-03: lost acknowledgement preserves transaction identity and indeterminate state until observed.
- MATRIX-04: deleted/redacted content does not re-enter context or replay after reconnect/restore.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Matrix is a digital sensory/effect organ, not a source of user authority beyond authenticated enrolled scope. No direct agent-store writes. Rollback must retain sync and dispatch identities and current revocation/redaction frontiers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

### Executable path and state owners

Supervisor's `start_matrix_companion`/`recover_matrix_companion` launches the
existing per-Agent Matrixd. `runner::run` acquires the canonical process lock,
opens `MatrixDurableStore`, connects through Agentd to its owning App Server,
restores/logs in the SDK and commits an initial durable sync before exposing
recovery or readiness. It then supervises sync, inbox dispatch, App Server event
projection, the existing durable outbox sender, local control and Agentd health.
No separate observer daemon or shared multi-Agent writer is composed.

- **Sync admission:** `MatrixSdkClient::sync_durable_once` and
  `MatrixSyncComposer::commit_response` in `hepta-matrix-sdk/src/sdk.rs` and
  `sync.rs`. `MatrixIngress` filters enrolled room/sender/mention; the live V2
  owner commits normalized mutations/tombstones with the cursor. Standalone
  `MatrixIngress::ingest` does not advance `/sync`.
- **App Server admission:** `MatrixRuntime::process_event` and `recover_pending`
  in `hepta-matrixd/src/runtime.rs` consume already durable inbox records and
  preserve room-thread/client-message identities. They do not own sync dedupe or
  cursor advancement. Lost dispatch acknowledgement is reconciled through the
  owning App Server, not submitted as a new independent turn.
- **Durable send:** `run_outbox_sender`/`dispatch_outbox_once` in
  `hepta-matrix-sdk/src/outbound.rs` use the store's stable transaction identity
  and exact binding/generation. The SDK sends to the configured enrolled room.
  `Sent` means the homeserver returned the send event ID; it is not human reading
  or a separate sync-echo observation.
- **Target observer:** `MatrixSendObserver::prepare_send`/`observe_send` in
  `hepta-matrixd/src/send_observer.rs` are an in-memory supplied-input state
  machine. They do not authenticate grants/observers, persist to the outbox or
  have a runner caller. The standalone observer binary exits 64.
- **Storage:** the per-Agent `matrix_1.sqlite3` owns inbox/thread/dispatch/outbox,
  sync and control state. Checked-in migrations and V2 tombstones preserve
  durable record interpretation. Migrations 0006 and 0007 add exact admitted-turn
  observation cursors and parked uncertainty; migration 0008 scope quarantine
  excludes affected work without deleting already-issued dispatch identity.
  SDK state/cache and session remain private
  under `matrix-sdk-0.18`. Agentd spawn generation and stable Matrix plane
  generation have distinct lifetimes.

### Adversarial source corrections and regression identities

- Control rechecks live lifecycle/dependencies after its mutation gate and
  before adapter effects; listener shutdown cancels and joins accepted
  connections. `ResolveApproval` transport success returns socket-write-only
  wire `Accepted` and retains the exact durable `resolving` decision. Only the
  matching authoritative `ServerRequestResolved` concludes resolution.
  `hepta-matrixd/src/control_lifecycle_tests.rs` covers queued fencing,
  dependency loss, shutdown cleanup and write-only disconnect/reopen.
- Coalescing checks the complete retained text prefix against 1 MiB inside the
  transaction. Claim selection excludes provably waiting replacement roots
  before LIMIT, while failed roots still settle their dependents.
  `hepta-matrix-store/tests/outbox_adversarial.rs` covers overflow rollback,
  one-record-page starvation and failed-root settlement.
- SDK and durable-owner storage admission reject symlinked directory ancestry
  and linked database/WAL/SHM/journal files. Sender claims one current eligible
  record at a time, checks cancellation
  before claim, bounds send by its remaining lease and timestamps completion with
  observed elapsed time. Exhausted retry uncertainty parks the same transaction
  for reconciliation without a new PUT or a terminal failure inference. The
  SDK request disables general HTTP retries, leaving attempt budgeting to the
  durable owner. Malformed ACK JSON/event-ID decoding stays retryable unknown
  delivery. Successful sync cycles have a 100 ms minimum cadence; mid-sync
  cancellation fences SDK/ingress and returns `Cancelled` for reconstruction
  from the durable Hepta cursor.
  `hepta-matrix-sdk/tests/durable_transport.rs` and
  `tests/support/outbound_boundaries.rs` cover the storage and sender boundaries.
  ACK classification has native unit coverage in `hepta-matrix-sdk/src/sdk.rs`.
  The sync cadence and mid-sync cancellation paths are source-inspected; no
  executable regression or pass receipt for those two paths is asserted here. Owner
  `tests/outbox_unresolved.rs` proves parked uncertainty across reopen; the state
  stays `InFlight` and only the issued attempt/physical transaction can settle
  it; coalesced aliases cannot settle another identity. Later permanent errors
  also park as `unknown_delivery` when an earlier attempt remains uncertain.
- Admitted-turn recovery shares a budget of 16 outer pages of 100 persisted turns
  per pass,
  persists a compare-and-set cursor bound to the exact current dispatch and
  requires full terminal items, original client identity and canonical input
  digest before final
  projection. `runtime/tests.rs` covers offline final replay and a turn older
  than 1600 records across restart. Completion clears the exact cursor
  transactionally. The bounded pending-inbox keyset window progresses past old
  pending rows and wraps without duplicate selection; its window frontier is
  process-local and restarts at zero. It does not recreate missing Core records.
  This bounds outer turn/RPC pages only: `ThreadTurnsList` Full items call
  `paginated_turn_full_items` without a total item/internal-page cap for each
  turn. Full-item hydration memory remains unbounded by this window; a
  five-second client RPC timeout does not cancel server-side hydration.
- Redaction of a begun, queued, admitted or completed dispatch commits the
  tombstone and quarantines the affected
  binding scope in actionable inbox/dispatch/outbox views. Legacy outbox input
  lineage is insufficient for a narrower cut, so all unsent output in that scope
  stops while other rooms continue. Already-entered effects retain their actual
  observations; quarantine does not assert they stopped. The raw issued
  dispatch remains available for exact Core identity tracking; neither local
  cancellation nor remote terminality is inferred. Quarantine is immutable and
  cannot self-clear; bounded inspection and `ResyncRequired` reason
  `dispatched_redaction_quarantine` expose the stop.
  Provider-context withdrawal and authenticated quarantine resolution remain
  separate requirements. Startup excludes quarantined thread resumes, recovery
  and projection; raw dispatch state remains forensic evidence.

These entries describe source and regression identities, not executed-pass
receipts. The exact-candidate test matrix is:

```sh
just test --locked -p codex-hepta-matrix-protocol -p codex-hepta-matrix-sdk -p codex-hepta-matrix-store -p codex-hepta-matrixd
```

Run from `codex-rs`. The Lane B source and synthetic-merge lanes both invoke the
real owners, including SDK/store integration tests. Native sync/recovery tests
live in `hepta-matrix-sdk/src/sync_tests.rs`, `gap_fill_tests.rs`,
`hepta-matrixd/src/runtime/tests.rs`, `runner_startup_tests.rs` and store
`tests/sync_mutation_v2.rs`/`sync_observation_v1.rs`.

### Remaining repository-controlled work

1. Wire independently issued current final-use operation/room/payload authority
   and revocation at the existing SDK send adapter. Room/revision/generation and
   digest equality alone do not implement `VerifiedUseToken` consumption.
2. Bind the stronger observation target and an authenticated reconciler to the
   canonical durable transaction/outbox. Retain the send acknowledgement as a
   distinct claim, preserve parked uncertainty and avoid a second sender.
3. Resolve quarantined dispatched-source withdrawal and restore through the actual
   provider/context owners. Durable quarantine and initial-sync ordering do not
   prove already attached content was withdrawn or the provider stopped.
4. Compose the bounded gap-fill helper into the live sync composer: a limited
   timeline currently rejects without advancing the cursor. Tested helper
   behavior is not proof that live reconnect accepts gaps.
5. Add bounded history item pagination and an owner-side terminal/freshness seam.
   The outer 16 × 100 turn/RPC budget does not bound Full item hydration and
   client timeout does not stop the server's hydration work.
6. Enforce HTTP predecode byte admission and total retained inbox/outbox capacity.
   Bounded normalized events/checkpoint work operate after SDK decoding;
   `event_capacity` bounds batch/change/control/scrub work, not total stored data.
   V2 mutation/decision journals each have fixed 65536-record lifetime ceilings
   without rotation. Implement authenticated retention/archival and measure
   target-host resources; pilot queue ceilings remain targets where no native
   enforcement is identified.

### External qualification and activation gates

Independently provisioned enrolled homeserver/user/device trust and encryption,
current authority/configuration trust, explicit paired-release/schema
compatibility, real transport/rate-limit/reconnect,
backup/restore non-resurrection, measured capacity and independent acceptance
remain separate. The checked-in `real-synapse-e2e` hermetic fixture uses its
explicit macOS/Homebrew/Docker tool profile; it is not run by ordinary default
Rust tests and is not a production deployment or acceptance receipt.

Current source bindings and operating references are
[IMPLEMENTATION_MAP.json](../../../docs/modules/channel.matrix/IMPLEMENTATION_MAP.json),
[the technical guide](../../../docs/modules/channel.matrix/TECHNICAL.md) and
[Lane B composition](../../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md).
Production, independent acceptance, activation and release remain false.
