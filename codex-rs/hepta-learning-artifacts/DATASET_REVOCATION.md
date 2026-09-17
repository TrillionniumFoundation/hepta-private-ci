# Dataset withdrawal and artifact-owner revocation

This module uses two complementary mechanisms for dataset withdrawal:

1. `DatasetWithdrawalRegistry`: the persistent append-only tombstone authority used
   to deny future V2 admissions;
2. `prepare_dataset_revocation`: a bounded staging operation that revokes already
   registered V1 artifact projections whose dataset support matches the requested
   withdrawal.

Neither mechanism authenticates people, performs physical erasure, selects a
replacement artifact or changes a running process.

## 1. Persistent withdrawal authority

`DatasetWithdrawalRegistry` is an append-only digest chain. A notice binds:

- notice identity;
- dataset digest;
- source tombstone digest;
- authority identity;
- credential-chain digest;
- signing-key digest;
- authority epoch;
- issue time.

Exact retries are idempotent; changed semantics under a reused notice identity
conflict. The in-memory snapshot is exactly replayable.

The durable representation is written with
`write_withdrawal_registry_snapshot`. It is create-only, bounded, file-digest
checked and bound to `WithdrawalAuthorityDomainV1`:

```text
(registry_id, scope_digest, authority_id, authority_epoch)
```

This domain binding is required because a head digest alone does not identify an
authority namespace. In particular, independent empty withdrawal registries all
have a zero head.

V3 artifact admission binds both the exact current withdrawal head and the domain
digest. Publication revalidation requires the same current domain/head; a stale
or cross-domain admission fails closed.

## 2. Dataset-to-existing-artifact revocation preparation

`prepare_dataset_revocation` addresses artifacts that are already in the stable V1
registry.

The host must authenticate the source withdrawal notice and establish that the V1
manifest's `support_digest` is bound to the relevant dataset snapshot. The API does
not infer dataset membership from prose or reconstruct row-to-dataset dependencies.
Those mappings remain source/dataset-owner facts.

The operation takes:

- the current artifact registry;
- its expected chain head;
- operation identity;
- dataset digest;
- source-notice digest;
- evaluator identity.

It finds direct matches, sorts them canonically, and stages ordinary
`ArtifactEvent::Revoke` entries on a private clone. The caller's current registry is
never mutated. Existing lineage eligibility makes descendants unavailable when an
ancestor is revoked even if the descendant carries a different direct support
digest.

## 3. Retry, conflict and boundedness

Revocation operation identity is `(dataset_digest, operation_id)`. Per-target event
identity additionally binds artifact identity. The reason digest binds source
notice and evaluator.

Exact retries reuse identical records. Changed source notice/evaluator semantics
under an existing target identity conflict. Already-revoked artifacts from another
operation are reported separately rather than silently relabeled.

The preparation rejects:

- stale expected registry head;
- empty critical digests;
- no matching target;
- producer/evaluator collision;
- event identity conflict;
- bounded quota overflow.

There is no partial mutation of the caller's current registry.

## 4. Publication and acknowledgement order

Withdrawal authority and existing-artifact revocation must converge under one host
publication generation.

For a product publication the host must:

1. authenticate the withdrawal authority evidence;
2. append/persist the withdrawal registry successor;
3. prepare the V1 artifact registry revocation successor where applicable;
4. update lifecycle state where required by product policy;
5. prepare `ArtifactPublicationPlanV1` against the exact resulting heads;
6. persist and sync the immutable registry/withdrawal/lifecycle files;
7. acknowledge their exact receipts;
8. seal and persist the publication commit;
9. publish the authenticated current-generation pointer;
10. only after durable current publication, acknowledge the source/outbox operation.

A crash before the current pointer changes may leave immutable orphan files but
must not acknowledge or expose a partially published generation.

Two synced files are not a distributed transaction. The publication transaction
is a fail-closed receipt contract; the host still owns writer fencing, commit-file
placement, current-pointer atomicity and directory durability.

## 5. Multi-dataset provenance

V2 manifests carry an explicit bounded set of source dataset digests. Current V3
admission checks every source digest against the persistent withdrawal registry.

The stable V1 registry contains only its older `support_digest` projection and is
not a lossless representation of V2 provenance. Therefore:

- future admission safety comes from the persistent V2 withdrawal registry;
- existing V1 revocation requires an authenticated source-to-support mapping;
- a multi-dataset training run must not pretend that one V1 support digest contains
  arbitrary unregistered component membership.

If an external dataset service uses aggregate snapshots, that service must define
and authenticate the aggregate/component relationship supplied to the artifact
owner.

## 6. Explicit remaining external obligations

This module does not prove:

- complete row-to-model influence;
- deletion from external caches/backups;
- physical erasure;
- rebuild correctness after withdrawal;
- production rollout of a replacement;
- authentication of source/authority signatures;
- product writer fencing/current-pointer durability;
- operator acceptance or release.

Those are independent gates.

## 7. Regression coverage

The source tests cover both sides of the withdrawal boundary:

- persistent withdrawal blocks future V2 admission and replays exactly;
- V3 admission binds exact withdrawal head and authority domain;
- a different authority domain with the same zero head is rejected;
- a later withdrawal invalidates an earlier admission before publication;
- durable withdrawal file roundtrip rebuilds the same semantic head;
- staged V1 revocation covers direct targets/descendants, stale heads, retries,
  changed semantics, role collisions, prior state and quotas;
- publication transaction refuses to seal after partial durability.

These are source tests, not release evidence. Exact-head and actual-base synthetic
merge qualification, strict lint, formatting and independent/product review remain
mandatory.
