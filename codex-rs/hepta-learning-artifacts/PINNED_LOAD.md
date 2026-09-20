# Pinned candidate read boundary

`load_pinned_candidate` joins two existing read-only checks into one bounded
operation: exact registry snapshot recovery and exact candidate payload
recovery. The caller supplies a complete `ArtifactManifest` and an externally
retained `RegistrySnapshotReceipt`. Every manifest field must match the
recovered registry before any payload bytes are returned.

The loader accepts already-open `File` capabilities. It does not traverse a
path, create, truncate, repair, write, execute, install, select, activate,
promote, retire, or roll back an artifact. It does not read or write the
learning ledger and cannot create a decision, observation, outcome, or credit
event.

## Trust and freshness

The host must authenticate the expected receipt independently of the snapshot
file. Deriving an expected receipt from the file under inspection only proves
self-consistency and is forbidden. The host also owns trusted parent traversal,
file ownership, scope binding, and generation fencing.

A successfully verified snapshot is not necessarily the newest snapshot. The
loader proves lineage eligibility only relative to the supplied snapshot. It
cannot infer revocation freshness and exposes no `selected`, `active`,
`current`, or `fresh` state. Before runtime inspection or use, the host must
obtain the currently authorized receipt from an independent durable witness and
fail closed when that witness is missing, stale, or unauthenticated. An older
snapshot must never be substituted to make a quarantined or revoked candidate
eligible.

## Validation and failure

The operation performs these checks in order:

1. `read_registry_snapshot` validates receipt bounds, complete file digest,
   scope binding, canonical encoding, event replay, and chain head.
2. The recovered manifest for the pinned artifact ID must equal the supplied
   manifest in every field.
3. `read_candidate_payload` verifies that the candidate and all ancestors are
   eligible in that snapshot, then checks payload size and content digest.

Any failure returns no payload. `PinMismatch` covers an absent artifact or any
manifest drift. `Storage` preserves the existing bounded storage error for
snapshot, eligibility, locking, I/O, or payload failures. The loader does not
fall back to a prior snapshot or alternate eligible candidate.

## Revalidating a cached consumer

`RevalidatingCandidate::new` consumes a verified loaded candidate. Before each
use, `with_current` accepts a host-opened file and an independently authenticated
current receipt. It checks the scope binding, nondecreasing record count and
actual previous chain prefix (including longer-fork rejection), then checks the
exact manifest and all ancestor eligibility before invoking the read-only
consumer. It does not reread or retrain the immutable payload.

Every failed refresh closes that consumer permanently. Restoring an old snapshot
cannot revive it: explicit admission of a new consumer is required. The host
still owns latest-view discovery, publication/use serialization, body generation
and the final effect boundary. Cached output is not a future-use capability.
