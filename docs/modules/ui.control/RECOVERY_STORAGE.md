# ui.control scoped recovery storage

## Purpose and authority boundary

The scoped recovery store exists to preserve an exact operation identity before a browser request can cross the transport boundary. It is not a runtime ledger, an authorization cache, or terminal evidence. The durable backend operation ledger and the runtime owner remain authoritative for admission, execution, lookup, and terminal state.

A local record can therefore require a lookup, but it can never prove success. A timeout, browser crash, storage fault, or missing acknowledgement must not cause a new operation ID to be dispatched as a replacement for an unresolved identity.

## Scope and key layout

A scope digest binds the exact API endpoint, recovery namespace, authenticated identity, and protocol version. Each scope uses:

- one directory key with schema `hepta.ui-control.scoped-recovery-directory.v1`;
- one exact record key per operation with schema `hepta.ui-control.scoped-recovery.v2`.

The directory contains only sorted operation IDs and local maintenance states. It does not contain credentials, authority, terminal facts, or permission decisions. Ready entries contain no operation payload. Transient entries contain the exact immutable identity fields needed to repair an interrupted local transition without adopting a different record.

The default scope capacity remains 1,024 records, with a hard configurable maximum of 4,096. Each operation record remains bounded to 8,192 bytes. The directory is bounded to 1 MiB. These are resource limits, not evidence that a runtime operation is accepted or complete.

## Directory states

| State | Meaning | Recovery rule |
|---|---|---|
| `reserving` | The directory transition was durable, but `prepare()` has not yet completed. No caller may dispatch from this state. | Under the scope lock, an absent record removes the entry; an exact present record is removed because the admission handoff did not complete. |
| `ready` | The exact record and directory entry were durably written before `prepare()` returned. The operation may or may not have crossed the network boundary. | Restore the exact record and query the backend by operation ID. Never infer success and never submit a replacement. |
| `removing` | Exact backend terminal evidence authorized local cleanup, but cleanup may have been interrupted. | Under the scope lock, an absent record removes the entry; an exact present record returns to `ready` so later cleanup can retry. |

A crash after the final `ready` write but before the caller observes `prepare()` is intentionally conservative: the record survives and is resolved by authoritative lookup. A crash before `ready` cannot create dispatch authority and is repaired as an uncompleted local reservation.

A `ready` directory identity without its exact operation record is never interpreted as completed or harmless. An unlocked load re-reads the same directory entry after observing a missing record: it tolerates only a verified concurrent transition away from `ready`, such as terminal cleanup already marked `removing`. If the identity is still `ready`, loading fails closed with `directory_record_missing`, retains the directory for diagnosis, and prevents the browser from silently hiding a possibly dispatched operation.

## Admission sequence

For a new operation, `prepare()` holds the scope Web Lock and performs the following order:

1. read and validate the exact scope directory;
2. reconcile only interrupted local transitions;
3. reject an existing conflicting identity, or return `UI_CONTROL_AMBIGUOUS_SUBMISSION` for an identical existing identity;
4. persist and read back a `reserving` directory entry;
5. persist and read back the exact operation record;
6. persist and read back the `ready` directory entry;
7. return to the client, which may then continue toward transport dispatch.

No session, permission, generation, revision, confirmation, or terminal decision is cached by the directory. The client and backend continue to perform their current checks at the existing boundaries.

The in-memory recovery importer validates and copies bounded canonical data before iteration. Array accessors are rejected without invocation, and inherited iteration hooks cannot hide or substitute records. The import then joins compatible pending identities atomically, preserves live dispatch promises and terminal history, and enforces the combined configured capacity. The canonical budget supports the full 4,096-record ceiling; an empty import is never a reset.

If an exact record already exists but directory repair fails, the result remains `UI_CONTROL_AMBIGUOUS_SUBMISSION` with `requestDispatched: true`. Storage degradation must never disguise a possibly dispatched identity as a fresh operation.

## Cleanup sequence

An absent V1 lookup is never cleanup evidence: a delayed admission may still arrive, so the exact ready record remains pending for bounded lookup. Terminal cleanup verifies the exact stored record against the independently observed terminal projection. For indexed records it then writes `removing`, deletes and verifies the record, and finally deletes and verifies the directory entry. Failed removal retains enough state for a later retry. An unindexed legacy record may be deleted only after the same exact terminal-identity verification; this compatibility path does not grant admission or discover other legacy records.

The browser cleanup queue remains a bounded, single-flight maintenance helper. Its memoization never certifies terminality and never authorizes replay.

## Migration and mixed-version deployment

When no directory exists, initialization performs one origin-wide scan bounded at 16,384 keys. It admits only exact records from the current authenticated scope, validates every discovered record, writes the directory, and thereafter uses direct directory and record keys. With a verified all-`ready` directory, reopening does not acquire the scope lock or enumerate unrelated origin keys.

The one-time scan is deliberately fail-closed. An oversized origin inventory, corrupt matching record, unavailable lock, denied write, or failed read-back leaves original data intact and disables new mutations for that scope.

Old browser code does not maintain the directory. A production rollout must therefore avoid mixed-version mutators:

1. stop or revoke mutation-capable sessions for the old asset version;
2. deploy the exact qualified assets;
3. invalidate cached HTML and force a full reload, including all long-lived tabs;
4. restore mutation permission only after the new page reports a healthy scoped directory and backend lookup path;
5. retain the old records until authoritative lookup resolves every indeterminate identity.

The externally accepted operational receipt must include the exact `mixed-version-mutation-fence` case. That case binds the exercise to the source-head browser build manifest and records that old mutation sessions were revoked or drained, cached HTML was invalidated, no legacy mutation session remained active, a stale client mutation received `401` or `403`, and the backend ledger contained no operation created by that rejected attempt. A checklist or top-level success boolean cannot replace these fields or their retained raw-evidence digest.

Do not delete the directory to “retry migration,” and do not clear local storage to regain availability. Either action can hide an identity that may already have crossed the transport boundary.

## Diagnostics

`ScopedRecoveryStore.diagnostics()` returns only bounded local maintenance counts: directory schema, entry count, capacity, counts by local directory state, and the number of keys examined by this instance during first migration. It exposes no operation IDs, reasons, credentials, session IDs, digests, or authority decisions.

Storage errors include a stable `details.storageReason` suitable for redacted telemetry. Current categories distinguish endpoint/identity errors, unavailable storage or locks, migration inventory and enumeration failures, directory corruption or scope mismatch, record corruption or scope mismatch, a ready directory identity with no exact record, capacity exhaustion, write/read-back failure, removal failure, and interrupted-transition repair failure. Raw storage values and unrestricted operation reasons must not be logged.

## Incident procedure

When the store fails:

1. disable new mutations while retaining read-only runtime diagnostics;
2. record the stable error code and `storageReason`, exact candidate build identity, deployment ID, and affected scope metadata without raw credentials or operation reasons;
3. preserve the directory and all matching records byte-for-byte;
4. resolve every visible or retained operation ID through the durable backend ledger;
5. repair quota, lock, browser-policy, or corruption causes without fabricating a terminal result;
6. reload the exact qualified browser build and confirm directory initialization;
7. restore mutation permission only after backend lookup, identity, permission revision, and generation fencing are healthy.

A malformed directory or record is retained for diagnosis. There is no bulk-clear recovery path.

## Qualification coverage

Repository tests cover:

- one-time bounded legacy migration and no subsequent origin enumeration;
- 20,000 unrelated same-origin keys after directory initialization;
- cross-tab duplicate admission and capacity checks under the scope lock;
- crashes before and after the final `ready` write;
- interrupted removal and conservative restoration;
- a missing record under a still-`ready` identity failing closed, while a verified concurrent `removing` transition remains readable;
- corrupt directory and record retention;
- existing-record ambiguity even when directory repair fails;
- terminal cleanup of an exact unindexed legacy record;
- 1,024 terminal records across two stores without repeated origin enumeration;
- sanitized store and cleanup-queue diagnostics.

These tests qualify repository behavior only. They do not substitute for real backend durability, production identity integration, deployed security observation, independent assistive-technology review, operational exercises, or production approval.
