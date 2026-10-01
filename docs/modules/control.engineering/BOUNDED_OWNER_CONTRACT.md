# control.engineering: bounded owner and recovery contract

Date: 2026-09-28. Owner: developer-productivity. Deputy: architecture.

This supplement describes ordinary source changes in PR #1175, not a production
acceptance receipt. Read it with [TECHNICAL.md](TECHNICAL.md) and
[IMPLEMENTATION.md](IMPLEMENTATION.md). Existing design scope is retained.
The named composition is `EngineeringControlProduct`; its persistent fact owner
is the existing SQLite v10 `EngineeringStore`. No second persistent database,
executor, result ledger, release authority, or implicit deployment is introduced.

## Review baseline and claim discipline

The baseline reviewed for this change is commit
`4f6dace4ccb3370fa9972851ff78c959cba1d304` on
`codex/control-engineering-post-merge-closure-20260928`.
The original review's description of `verify_from_checkpoint`, a
`ControlEngineeringProductRuntime`, and three named runtime/native-mutation replay
failures is not an established fact about this pinned owner implementation.
The actual audit entry was `verify_audit_suffix`, which already checked the hash
chain but materialized an unbounded suffix. The extension tests imported public
names and a renewal type that were not yet available from the package; some
implementation text existed only in authoring patch scripts. This change addresses
the source that was actually inspected; it must not be presented as a verified fix
for test names or failure counts that have not been reproduced.

`STATUS.json` is a generated projection of source claim boundaries, not an Actions
result. `PUBLIC_API.json` is an export-name manifest, not proof that an operation
ran successfully. Both retain the existing generators. Every production,
independent-acceptance, activation and release claim remains false. Existing
implementation-map provenance must be refreshed and checked against the final
candidate before its old complete-mapping declaration is accepted for new code.
Qualification never repairs that mapping or writes new source to make a gate pass.

## Bounded audit suffix verification

### Entry points and limits

Normal product methods delegate to `audit_checkpoint.py`:

- `create_audit_checkpoint(now_ns=...)` performs explicit full-chain and owner
  snapshot validation. It remains a cold, potentially history-sized operation.
- `verify_audit_suffix(checkpoint, budget=..., through=...)` verifies the complete
  suffix up to a pinned cut or rejects. It never silently truncates a precise
  verification request.
- `verify_audit_suffix_page(checkpoint, budget=..., through=...)` verifies one
  contiguous bounded page and returns an `AuditSuffixPage` continuation.

`AuditVerificationBudget` defaults to 4,096 events and 8 MiB of encoded payload.
Hard input limits are 65,536 events and 64 MiB. Zero, negative values and booleans
are rejected. Metadata selection uses the indexed sequence interval and SQL
`LIMIT maximum_events + 1`. Before fetching any payload row, the implementation
checks cumulative payload-byte lengths, event count and fixed metadata bounds.
A single event exceeding the byte budget fails rather than returning a zero-work
continuation forever. These bounds cover returned metadata and encoded payload;
they are not a claim of an exact allocator/RSS upper bound for Python JSON objects.

### Snapshot, cut and integrity rules

Each call uses one SQLite read transaction for anchor lookup, metadata admission
and payload verification. A call starting without a transaction owns and ends only
its own read transaction. A call inside a caller transaction does not commit or
roll it back. Initial paging records `AuditReadCut(sequence, event_digest)`; all
continuations retain that cut, so concurrent later appends cannot move the goal.

Validation checks contiguous sequence, predecessor digest, canonical JSON bytes,
event type, timestamp, recomputed digest, and the derived event ID. Missing anchors,
missing rows, a truncated pinned cut, malformed payloads and inconsistent hashes
fail. `complete` means this segment reached the requested cut. The strict method
rejects an incomplete result. The output explicitly reports
`ownerSnapshotVerified: false`: verifying audit history is not re-verifying current
owner state against a historical snapshot.

### Trust and continuation boundary

A checkpoint must come from the caller's trusted retained anchor or the existing
external anchor-verification path. It is not authenticated merely because its
fields contain hashes. The returned `next_checkpoint` carries forward the original
owner-snapshot digest solely as the audit continuation context; it must not be
reinterpreted as a newly certified owner-state snapshot at the new sequence.
A trusted caller must retain the chain of page receipts and pinned cut. Accepting
an arbitrary caller-supplied unsigned continuation does not prove the omitted
prefix. No cached audit observation grants execution authorization.

## Incremental capacity observations on the same owner

`EngineeringControlProduct` creates one `StoreCapacityMonitor` for its exact owner
connection. The monitor maintains only audit-event and active-claim counts in a
SQLite TEMP table. Fixed TEMP triggers on the existing main tables update those
counts in the same transaction as normal owner writes. Rollback rolls back both.
TEMP objects disappear on connection close and do not alter the persistent v10
schema or its canonical main-schema validation.

This is a derived observation, not a second durable fact source. No grant, policy
approval, revocation result or signature decision is cached. The observation's
`capacityScope` is `owner_database`, not an unsupported cross-host resource-pool
claim. Actual reservations and admission remain with the existing owner.

Stable same-connection observations read the small projection rather than counting
all historical rows. Another connection's committed write changes SQLite
`data_version`, causing rebuild from current facts. Version is sampled around a
pinned main snapshot; concurrent churn retries at most three times, then returns
`capacity_observation_changed`. It does not relabel old counts with a newer version.
An observation in a caller-owned transaction uses real counts and invalidates the
cache generation, because the caller may later roll back.

Calibration occurs on startup reconciliation, explicitly through
`capacity_state(calibrate=True)`, or on the first observation after the configured
monotonic interval (default 60 seconds). It is not a background timer. Unexplained
drift quarantines the monitor until owner reopen. Initial rebuild, external-writer
invalidation and calibration still scan current tables; frequent external writes
therefore do not have the stable-owner hot-path performance guarantee.

TEMP counts may briefly become negative after a foreign connection creates a
claim and this connection settles it before refreshing. They deliberately do not
have a nonnegative database constraint: a stale derived counter must not block a
legitimate primary-state settlement. Invalidation/rebuild occurs before returning
an observation; a negative value without such an explanation fails closed.
Database page and WAL-file sizes remain physical samples, not one atomic sample
with logical counts (`physicalSamplesAtomicWithCounts: false`).

## Authenticated worker-registration renewal and replay

`WorkerRegistrationRenewalReceipt` and `renew_worker_registration` are ordinary
source in `worker_registration.py`, exported by the package and delegated by the
existing product. They are not installed by a qualification-time patch.

The command identity is `(worker_id, expected_revision)`. Its request fingerprint
covers the complete signed receipt, including predecessor profile, authority
identity, new worker identity, skills, paths, capacity and time window. The
canonical existing audit records the resulting revision, profile and receipt
digests. Reusing that identity with different receipt bytes is a conflict, even
when the resulting profile happens to match.

Replay first passes the currently configured signature verifier and requires an
active worker. A revoked worker or invalid/untrusted signature is rejected. An
exact committed result is returned without re-executing the renewal or requiring
the original execution window still to be live. This does not extend registration
expiry, change revision, reserve more capacity, append another event, or undo a
later renewal. The returned historical digest is not a new capability.

New execution validates the live signed window, exact current revision and
predecessor, monotonic observation time, non-regressing expiry, and currently
reserved capacity. Key/skill/path rotation with active reservations is rejected.
The guarded update and audit append share the central owner transaction. Its
nested savepoint permits continuation only after that operation has rolled back
without aborting the enclosing SQLite transaction. A whole-transaction failure
such as `SQLITE_FULL` marks the owner scope aborted: catching the error cannot
permit another write or a successful outer commit. Failed rollback cleanup closes
the connection and requires a fresh owner to reopen and validate durable state.
Process restart and ambiguous response loss query the same identity; they do not
generate a replacement command.

The retained-outcome lookup uses an exact bounded result from the canonical audit.
It can still scan renewal history; it is explicitly a cold-path limitation, not a
claim of constant-time indexed command lookup. A future schema migration may add
an owner-maintained indexed projection, but must preserve the same canonical
facts and atomic recovery rules rather than creating a second result authority.

## Regression inventory

`test_bounded_owner_regressions.py` adds 25 test methods, including subcases, on the
actual owner/product implementation. Coverage includes pre-payload count/byte
rejection; append-safe paging; corrupt metadata, hashes and payloads; missing
sequences; preservation of caller transactions; hot-path counting; external-writer
invalidation; rollback; drift quarantine; owner mismatch; cold reopen; settlement
before stale-counter refresh; exact/different/historical renewal replay;
signature/revocation; active-capacity rotation; audit-insert failure; two spawned
processes racing the same renewal; and exit immediately after a committed renewal.
Original tests remain intact.

`test_candidate_evidence_collector.py` adds seven collector-specific tests. These
exercise real subprocess success, failure and timeout, missing executables,
log-hash binding, rejected log-path injection, atomic JSON replacement, and later
checks continuing after an earlier failure. They do not substitute for runtime
regressions or external acceptance. Local verification performed while authoring
covered these seven collector tests and collector syntax only; the 25 owner tests
and full repository/merge checks require separate actual execution results.

## Reproducible read-only qualification

From a clean, final source checkout with Python 3.12 and the pinned quality tools:

```sh
python3 scripts/control_engineering_candidate_evidence.py \
  --source-commit "$(git rev-parse HEAD)" \
  --base-commit "$(git rev-parse origin/main)" \
  --output /absolute/new/path/outside/the/checkout
```

The source and base arguments must be immutable full commit IDs. The script tests
the source, then constructs a deterministic synthetic merge with the exact same
base, explicit ordered parents and fixed Git identity/time. This local Git object
is not pushed, merged into main or treated as an approval. A conflict is retained
as failed setup evidence, never as a successful merge lane.

Each lane independently records command arguments, exit codes, timeout/launch
errors, log byte lengths and SHA-256 digests. It records source/base/tested commit
and tree identities, parents, collector digest, workflow SHA/run/attempt, runner
image, Python and Git identity. Coverage, test totals, failures and skips are
retained. Missing execution, a failed command, an empty suite, skipped tests or a
changed tracked tree prevents the collector's qualification flag. Source claims,
independent acceptance, production acceptance and release remain separate.

The workflow has `contents: read`, exact checkout and no persisted credentials.
It does not execute the old source-patch scripts, regenerate source during tests,
commit, push, normalize unrelated module documents, or remove itself. It retains
failure logs even when the state/API/document checks fail. Runtime tests therefore
still run and are not masked by an earlier stale-document error.

## Remaining acceptance boundaries

Successful collector unit tests are not full source qualification. A pushed
candidate, a queued Actions job, an old passing run, a generated status file and a
fixture signature are not acceptance. Before closing this module, retain passing
applicable checks for the final source and fixed merge, refresh/check the canonical
implementation map, obtain actual strong-sandbox evidence where required, and
obtain independent semantic review and applicable externally witnessed
fencing/audit/key-custody/deployment/rollback/operator receipts.

Do not fabricate a read-cut/outbox/dispatcher-ACK path solely to match an inaccurate
review description. Exercise the existing durable integration-queue and worker
lifecycle paths, and require a concrete native consumer/transport contract before
claiming a separate end-to-end path. External systems are neither provisioned nor
accepted by this change. No production enablement flag is switched on.
