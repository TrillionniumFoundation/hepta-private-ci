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

The initial pinned load still requires an independently retained receipt; deriving
that receipt from the file under inspection only proves self-consistency and is
forbidden. Final-use revalidation is stronger: `LearningArtifactOwnerHost` /
`LearningArtifactOwnerService` discovers and verifies signed CURRENT, while a
read-only proxy uses
`ArtifactOwnerVerifierV1::verify_current_registry_view_with_admission_closure`
for full V2/V3 eligibility. `verify_current_registry_view` retains signed V1
compatibility verification and supplies no absent source/expiry facts.
Both routes issue opaque `VerifiedCurrentRegistryViewV1` values whose complete
admission evidence is available through `full_admission`. The host also
owns trusted parent traversal, file ownership, scope binding, and generation
fencing.

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

## Complete provenance and legacy migration

The V1 pinned loader preserves exact historical V1 behavior. V1 alone cannot
prove multiple dataset inputs, all V2 predecessors or manifest expiry. A strict
owner CURRENT read loads `admissions/{manifest_digest}.admission` for every
registration, matches the immutable publication intent/checkpoint and exact V1
projection, and computes eligibility through `admission_closure.rs`.

All parents must be earlier registered compatible generations. Every source
dataset must remain outside the current authenticated withdrawal frontier, and
the selected artifact and all parents must be current eligible candidates within
their full manifest expiry windows. A withdrawn secondary source or an unavailable
parent blocks a descendant even when that relationship is absent from V1.

Missing sidecars fail closed in strict mode. Exact backfill requires the original
complete admission and its historical registration checkpoint; it cannot invent
provenance or reuse an older CURRENT floor. Admission sidecar recovery validates
historical timestamps, while use-time eligibility checks current expiry. Explicit
legacy V1 inspection is a separate compatibility operation with narrower evidence.

## Revalidating a cached consumer

`RevalidatingCandidate::new` consumes a verified loaded candidate. Before each
use, public `with_current` accepts only `VerifiedCurrentRegistryViewV1`. External
callers cannot construct that type from a bare file/receipt: the artifact owner
or `ArtifactOwnerVerifierV1` must first verify the signed CURRENT head, signer
context/authority epoch, exact registry binding and immutable snapshot. The
candidate then checks nondecreasing record count and the actual previous chain
prefix (including longer-fork rejection), exact manifest and owner-view
eligibility before invoking the read-only consumer. It does not reread or
retrain the immutable payload.

The first full-provenance view permanently fixes that consumer to strict mode;
a later V1-only view cannot downgrade it. An independently selected consumer also
retains its verified owner-trust binding and the selection's strictness at load.
Strict views expose `verified_at() = Some(now)`; compatibility views expose
`None`. APIs that receive an explicit use time require the strict verification
time to match it. The CURRENT provider still owns latest-view discovery for each
call and serialization with the final effect boundary.

Every refresh rejected by `with_current` closes that consumer permanently,
including a panicking consumer. Obtaining an authenticated view happens before
that method: when CURRENT discovery or verification fails, the host must discard
the cached consumer itself. The Agentd ranking host enforces this by taking the
consumer out of its cache before requesting CURRENT and restoring it only after
successful use. Restoring an old snapshot cannot revive a closed consumer:
explicit admission of a new consumer is required. The host
still owns latest-view discovery, publication/use serialization, body generation
and the final effect boundary. Cached output is not a future-use capability.
