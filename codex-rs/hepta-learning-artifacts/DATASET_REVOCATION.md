# Dataset notice to artifact-owner revocation preparation

This is a bounded ART-1/ART-2 and unlearning-lineage integration sub-slice under
the existing global plan. It adds no canonical wire variant, source-ledger writer,
selection service, trusted identity or physical-erasure claim.

## Exact supported relationship

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

## Explicit remaining limits

This is a snapshot-local invalidation batch, NOT a persistent dataset tombstone.
The host must retain the source withdrawal and deny new dataset-dependent artifact
admission; otherwise an entirely new artifact could be registered later. A retry
against a newer head can invalidate newly discovered direct targets, but cannot
prove that all external caches, models or backups were covered. Rebuilding without
the dataset, exact source membership, independent credentials, production rollout,
physical erasure and backup non-resurrection remain separate gates.

Eight regression functions cover multi-target/descendant invalidation, stale and
invalid requests, exact retry, changed semantics, late role collision, prior
revocation/quarantine, quota and real-file persist/reopen/current-witness rollback.
The original registry and storage suites are retained. The new functions are test
source, not executed evidence; source-head, actual-base merge, strict lint,
formatting, full product matrix and independent review remain mandatory.
