# Artifact publication transaction boundary

This document defines the crate/host transaction for publishing one admitted
learning artifact. It closes the gap between V2/V3 admission and the durable V1
registry without pretending that the V1 single-predecessor manifest can encode
all V2 multi-parent lineage.

## Owned state and exact commit

The crate validates and binds four immutable facts:

1. the V3 withdrawal-bound admission;
2. the V1 artifact-registry snapshot receipt;
3. the scoped dataset-withdrawal snapshot receipt;
4. the lifecycle-journal snapshot receipt.

`prepare_artifact_publication_v1` verifies that all three durable snapshots
share one nonzero host store binding, that their receipts match the exact
in-memory heads and record counts, that the V3 admission is still valid against
the current scoped withdrawal registry, and that the corresponding V1 registry
manifest matches the V2 artifact on kind, generation, bytes/content digest,
objective, producer, compatibility profile and encoded size.

The result is `ArtifactPublicationCommitV1`. Its digest additionally binds the
registry/scope identity, predecessor publication digest, every durable file
digest/head, the admission digest and commit time. It carries
`AuthorityPosture::DENY_ALL`; creating or reading it grants no selection,
activation, promotion or release authority.

## Durable order and single visibility point

The host transaction is:

1. create and sync the candidate payload;
2. create and sync the registry snapshot;
3. create and sync the scoped withdrawal snapshot;
4. create and sync the lifecycle snapshot;
5. prepare, create and sync the publication commit marker;
6. synchronize containing directories as required by the target filesystem;
7. atomically replace the authenticated current-publication pointer with the
   new commit identity;
8. only after step 7 acknowledge publication to upstream orchestration.

Steps 1-6 are staging. Existence of any staged file is not publication. The
single visibility point is step 7. The current pointer must be protected by the
host's writer fence and must name an independently retained
`ArtifactPublicationCommitReceiptV1` or equivalent authenticated lookup key.

A host must never update the current pointer first and fill in dependent files
afterward. A reader must never infer "current" by directory enumeration or
largest generation number.

## Crash and retry matrix

| Failure point | Required visible state | Recovery |
| --- | --- | --- |
| before any snapshot sync | previous publication | discard/reconcile staging |
| after one or more snapshot syncs | previous publication | verify receipts; reuse only immutable exact objects or stage fresh names |
| after commit marker sync, before current-pointer replace | previous publication | verify commit marker, then retry only the final fenced pointer operation |
| during current-pointer replace | previous or new complete publication, never a partial mix | reopen authenticated pointer and verify referenced commit |
| after current-pointer replace, before upstream acknowledgement | new publication | replay acknowledgement idempotently from the exact commit digest |

The regression `crash_before_current_pointer_publish_keeps_previous_generation_visible`
exercises the central invariant: a fully staged new commit is still invisible
until the final pointer replacement.

## Replay and freshness

`read_artifact_publication_commit` verifies exact file bytes and recomputes the
commit digest. `verify_artifact_publication_commit_v1` additionally checks the
expected predecessor publication digest and the current withdrawal/lifecycle
heads. Restoring an internally valid old commit is not enough to establish
freshness; the host supplies the currently authenticated pointer and authority
fence.

Historical lifecycle replay is intentionally different from new mutation
authorization. Durable recovery validates the actor evidence and its binding to
the event's historical `occurred_at`; it does not require that credential to
remain unexpired at reopen time. A new lifecycle append still requires the actor
credential to be current at the supplied `now`.

## Host obligations and non-claims

The crate does not own a cross-filesystem transaction manager, directory fsync,
remote object-store compare-and-swap, service identity, signing key, process
lease, production selector or rollout controller. Those are host boundaries.
The host must provide a race-resistant trusted directory capability where parent
mutation is adversarial, serialize publication writers, retain receipts outside
the suspect files, and reconcile unreachable staging objects.

The create-only storage layer performs best-effort cleanup of empty owned Unix
staging files and offers `CreateOnlyArtifactFile::create_under` for lexical and
canonical-parent containment. These are defense-in-depth controls, not a claim
of `openat2`/dirfd-equivalent path confinement on every platform.
