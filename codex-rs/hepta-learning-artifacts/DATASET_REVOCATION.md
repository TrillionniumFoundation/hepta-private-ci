# Dataset withdrawal and artifact-owner restrictions

This is a bounded ART-1/ART-2 and unlearning-lineage integration sub-slice under
the existing global plan. It adds no canonical wire variant, source-ledger writer,
selection service, trusted identity or physical-erasure claim. The native owner
now has full V3 sidecar recovery and a durable restriction-publication saga;
the retained V1 batch-preparation helper is described separately below.

## Complete-source withdrawal through the owner

`LearningArtifactStatePublishRequestV1` carries an
`ArtifactOwnerStateIntentV1` for `InstallWithdrawalFrontier`, `Revoke` or
`Quarantine`, both expected predecessor heads, the evaluator/reason and an
externally signed CURRENT and a separate domain-separated state authorization.
`LearningArtifactStatePublishRequestV1::authorization_signing_bytes()` binds the
whole intent and next frontier with bounded authorization times. The trusted
external head signer must sign it even if no artifact changes and CURRENT keeps
the same head. The authenticated scoped withdrawal frontier
must extend the existing exact prefix. The owner resolves source membership from
complete admissions at `admissions/{manifest_digest}.admission`; it does not treat
a V1 support digest as an arbitrary dataset digest.

Each sidecar preserves every source dataset and every parent. Its manifest pin
comes from the independently witnessed registry, its admission pin from the
original registration checkpoint and its scope from the configured owner.
The strict read join checks matching V1 projection, parent registration order,
kind/objective/generation compatibility, current expiry and candidate state.
A withdrawn secondary source blocks the artifact; a revoked, quarantined,
expired or otherwise ineligible parent blocks every descendant through all V2
parent edges, including multi-parent edges absent from the V1 projection.

`owner_state.rs` / `owner_state_storage.rs` implement
`Prepared -> SnapshotsDurable -> WitnessDurable -> Acknowledged`.
Registry and scoped withdrawal snapshots become durable before publishing the
signed successor head and terminal checkpoint. A pending operation fences
unrelated publication. Restart recovers the exact operation and withdrawal
frontier, while exact retries preserve the original operation and lease identity.
CURRENT read consumers then observe the joined restrictions before use.

New owner deployments use `LearningArtifactOwnerService::open_v2` with the V1
owner configuration plus the independently retained
`required_withdrawal_head_digest`. Recovery proves both the CURRENT and
withdrawal floors. `install_withdrawal_frontier` accepts only identical no-ops;
an advancement returns `DurableStatePublicationRequired` and must be durably
published through the state saga.

The deployment dataset authority authenticates the withdrawal notice and latest
frontier; the artifact owner verifies and persists their typed digest-bound effect.
This separation is an implemented trust input, not permission for the store to
fabricate withdrawal or independent acceptance evidence. Physical media erasure,
source outbox acknowledgement, cache/backend deletion and backup retention remain
the respective owner/deployment responsibilities.

## Historical sidecar migration

V1 compatibility inspection remains available. Strict owner use of an older store
fails closed until every registration has its original full admission sidecar.
`LearningArtifactOwnerHost::backfill_artifact_admission` requires a current writer
lease and exact historical admission/checkpoint/scope/head/projection identity.
It creates missing evidence only; it does not alter artifact state or grant use.
Historical recovery validates `admitted_at`, so an expired manifest's provenance
can still be restored while current eligibility remains denied.

## Retained V1 helper's exact supported relationship

The host must authenticate the dataset withdrawal notice and establish that the
artifact manifest's `support_digest` is bound to that exact dataset snapshot.
The API does not assume that every support digest represents a dataset, infer
membership from prose, or reconstruct row-to-dataset dependencies. Those mappings
and their completeness remain owned by source/dataset services. A multi-dataset
training run must withdraw its aggregate snapshot before using this operation;
a component dataset digest must not be substituted for the aggregate digest.

`prepare_dataset_revocation` takes the current artifact registry, its expected
chain head and an operation/dataset/source-notice/evaluator request. It finds
all directly matching manifests in that snapshot, sorts targets canonically,
and stages ordinary existing `ArtifactEvent::Revoke` entries on a private clone.
The original registry is never mutated. Existing ancestry eligibility makes
indirect descendants unavailable even when their own support digest differs.
An unrelated artifact and a clean rollback predecessor remain unchanged.

## Retry, conflict and atomic preparation

Operation identity is `(dataset_digest, operation_id)`. Each target event ID
binds that identity and artifact ID. Its reason binds the source notice and
evaluator too. Exact retries reuse existing events; changed source notice or
evaluator on an existing target returns identity conflict. Already revoked
artifacts from other operations are reported separately, not silently relabeled
as newly revoked. Quarantined targets can advance to revoked.

Stale expected head, empty digests, no matching targets, any producer/evaluator
collision, identity conflict or quota breach rejects the entire preparation.
There is no partial mutation of the caller's registry. Bounds are 4096 registry
records including new revocations and 256 direct targets; a larger operation
needs a separately specified bounded delivery plan, not truncation.

## Persistence and acknowledgement order

The returned candidate and summary are PREPARATION only. The host must serialize
writers under its current fence, persist the candidate using the existing
`write_registry_snapshot`, synchronize parent directories as required, durably
publish the new independent witness with an exact predecessor check, and only
then acknowledge the source outbox notice. A crash or unknown acknowledgement
requires reopening against the current witness and retrying the same operation.
Two file syncs do not create a distributed transaction. This function does not
implement the source outbox, witness service, fence or source acknowledgement.

The target head must be rechecked at publication. Another writer's concurrent
changes invalidate the candidate. Readers and rollback must use the current
witness and revocation history, never an old snapshot plus its old receipt.
No selected artifact or running process is changed by preparation or persistence.

## V1 helper limits and external deletion evidence

`prepare_dataset_revocation` itself remains a snapshot-local invalidation batch;
it is not the persistent tombstone store. The persistent future-admission guard is
the separate scoped `DatasetWithdrawalRegistry`. A host records the authenticated
withdrawal there, persists it with the canonical withdrawal snapshot adapter, and
uses scoped V3 admission so every later dataset-derived manifest is checked against
that exact withdrawal frontier.

The withdrawal registry closes the former "new artifact can silently reuse a
withdrawn dataset" source gap. It does not prove that all external caches, model
stores, backups or physical media were erased. A retry against a newer artifact
registry head can invalidate newly discovered direct targets; rebuilding without
the dataset, exact source membership, independent credentials, production rollout,
physical erasure and backup non-resurrection remain separate gates.

Eight regression functions cover multi-target/descendant invalidation, stale and
invalid requests, exact retry, changed semantics, late role collision, prior
revocation/quarantine, quota and real-file persist/reopen/current-witness rollback.
The original registry and storage suites are retained. The new functions are test
source, not executed evidence; source-head, actual-base merge, strict lint,
formatting, full product matrix and independent review remain mandatory.


## Persistent withdrawal scope

For V3 admission the withdrawal registry is created with
`DatasetWithdrawalScopeV1 { authority_domain_id, registry_id, scope_id }`.
That scope participates in the scoped genesis/head derivation and admission
digest. An unscoped registry cannot issue a V3 admission, and a receipt admitted
under one scope cannot be published under another scope merely because both
registries happen to contain the same event sequence.

`write_dataset_withdrawal_snapshot` and its contained `*_beneath` variant
persist canonical scoped state. The read path requires an independently retained
receipt binding the scope digest, chain head, file digest, record count and
encoded byte count before replay returns a registry.

### First-publication withdrawal bootstrap

Before any artifact CURRENT exists, `LearningArtifactOwnerService::publish_withdrawal_bootstrap`
accepts `LearningArtifactWithdrawalBootstrapRequestV1` signed by an externally configured
head signer in the separate `hepta.learning-artifacts.withdrawal-bootstrap.v1` domain.
The authorization binds operation, registry, storage binding, scoped predecessor and
successor withdrawal heads, signer, epoch and validity interval. It grants no artifact
selection or registry head. New bootstrap operations are rejected after CURRENT exists.
The exact withdrawal snapshot is persisted and synchronized before the immutable signed
`withdrawal-bootstrap/{operation-hash}.receipt`. Orphan snapshots do not advance recovery;
acknowledged records require their exact snapshot and signature. Recovery joins only
compatible prefix extensions. Exact retries cannot roll the live frontier backwards.
`open_v2` also applies the independently retained withdrawal head floor to this frontier.
Tests in `owner_state_tests.rs` cover unsigned mutation, stale authorization, first-publication
admission denial, exact retry, restart and missing acknowledged snapshot.
