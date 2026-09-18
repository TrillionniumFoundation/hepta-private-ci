# Immutable artifact storage boundary

This ART-1/ART-2 storage sub-slice adds actual file I/O to the existing artifact
registry. It is not a second registry, runtime selector or full learning loop.
The caller authorizes a target path, scope, receipt and current revocation view;
the crate owns the atomic final-component creation required by the write API. It
does not obtain credentials, install models or select a production artifact.

## Snapshot and payload API

The only safe writer capability is the opaque `CreateOnlyArtifactFile`. Its
`create(path)` constructor opens the final component with
`OpenOptions::create_new(true)`, read and write access, and mode `0600` on
Unix (subject to a more restrictive umask). That atomic operation must fail with
`AlreadyExists` whenever the target name already exists, including an empty
file, an acknowledged file truncated to zero bytes, or a symbolic link.

No conversion from an arbitrary `File`, raw descriptor or cloned handle into
`CreateOnlyArtifactFile` is permitted. The type exposes no underlying handle
and each writer consumes it. These restrictions make it impossible for safe
callers to relabel an existing empty inode as new. Reader APIs remain
file-capability based and accept independently opened read-only `File` values.

The required public writer signatures are:

```text
write_registry_snapshot(CreateOnlyArtifactFile, &ArtifactRegistry, Digest32)
write_candidate_payload(CreateOnlyArtifactFile, &ArtifactRegistry, &StableId, &[u8])
write_registry_head_witness(CreateOnlyArtifactFile, &RegistryHeadWitnessV1, &RegistryHeadRequirementV1, Digest32)
read_registry_head_witness(File, RegistryHeadWitnessReceipt, &RegistryHeadRequirementV1)
write_dataset_withdrawal_snapshot(CreateOnlyArtifactFile, &DatasetWithdrawalRegistry, Digest32)
read_dataset_withdrawal_snapshot(File, JournalSnapshotReceiptV1)
write_lifecycle_journal_snapshot(CreateOnlyArtifactFile, &ArtifactLifecycleJournalV2, Digest32)
read_lifecycle_journal_snapshot(File, JournalSnapshotReceiptV1, now)
```

`write_registry_snapshot` writes one new empty target and syncs it before
returning a `RegistrySnapshotReceipt`. `read_registry_snapshot` requires that
exact externally retained receipt, checks bytes and history, then rebuilds the
same `ArtifactRegistry` through its existing validation. Register, quarantine
and revoke retain canonical lineage semantics. There is no repair of truncation
and no fallback to old state.

The HEPTAR01 encoding is UTF-8/ASCII, newline terminated: magic, binding digest,
record count, then one pipe-delimited event per line. R records contain event ID,
artifact ID, kind tag, generation, optional predecessor, content/objective/support
digests, producer, compatibility digest and encoded size, in that order. Q and V
records contain event, artifact, evaluator and reason. IDs already prohibit pipes
and newlines. Re-encoding must match byte-for-byte, rejecting alternate integers,
line endings and other noncanonical input. Existing event and chain digest
algorithms are unchanged and checked after replay. The receipt binds scope,
record count, chain head, complete file digest and byte count.

The `HEPTAH01` head-witness channel is also create-only and bounded to 4 KiB.
It writes a canonical witness only after `validate_registry_head_witness` passes,
and reload verifies the independent file receipt plus the caller's current
generation, predecessor, authority-epoch and expiry requirement. It distributes
an authenticated host witness; it does not discover the newest path or grant
selection or activation authority.

Candidate payload functions verify current registry eligibility, byte length and
content digest. A revoked ancestor blocks loading descendants. Stored code or
model bytes are never executed. Snapshot limits are 4096 events and 8 MiB;
payloads are bounded by 64 MiB. Snapshot creation is O(history), bounded by the
pilot cap; this is not a high-frequency journal or hard-real-time controller.

## Failure and retry semantics

Validation occurs after the caller creates the opaque capability but before any
artifact bytes are written. Invalid binding, ineligible artifact or payload
mismatch therefore leaves a zero-length orphan for host reconciliation. It does
not authorize reusing that path: a second `create` must return
`AlreadyExists`.

After successful atomic creation, a nonzero length observed before the guarded
write indicates interference and returns `Indeterminate`. Lock contention
returns `Busy` without this writer writing bytes. A write or synchronization
failure is `Indeterminate`; the caller must reconcile the exact target and
expected digest. It must never truncate, overwrite, silently adopt or retry
through the same path. Removal of a proven orphan is a separately authorized host operation. An orphan
reconciler must start from authenticated committed-generation receipts, treat every
unreferenced create-only file as a candidate for review rather than proof of garbage,
apply an age/grace bound, and delete only inside the host-authorized storage root.
The crate intentionally exposes no recursive-delete or "clean directory" primitive.

## Host transaction and trust boundary

The host authenticates the scope, target parent, file ownership, identities and
receipt. Digests and differing evaluator strings alone do not authenticate
people or services. A current external revocation witness is mandatory before
any runtime use: a valid old snapshot plus its old receipt can still predate a
deletion. This module cannot infer the latest state from the suspect file. Never
use an older snapshot to make a revoked predecessor appear eligible for rollback.

The V2/V3 publication sequence is:

1. validate withdrawal-bound admission against the exact registry/domain/scope;
2. prepare an `ArtifactPublicationIntentV1` against the candidate V1 registry head;
3. create/sync the candidate payload and retain the digest returned by `write_candidate_payload`;
4. create/sync the canonical registry snapshot and retain its `RegistrySnapshotReceipt`;
5. finalize with the exact payload digest, current withdrawal head/scope and snapshot receipt;
6. only after receiving `ArtifactPublicationCommitV1` may the host atomically publish its CURRENT pointer or equivalent current-generation selector.

Finalization fails if the payload sync digest, withdrawal frontier/scope or durable snapshot head differs from the prepared intent. Two synced files alone are not a committed generation. A crash before commit may leave orphan files; a crash after commit must recover/publish the same authenticated commit identity rather than infer a new commit from file presence.

`create_new` protects the final path component from an existence-check race; it
does not authenticate ancestor traversal, retain a path-to-inode binding after
return, synchronize the parent directory or isolate hostile writers. Host path
containment is therefore a hard precondition: resolve or open the authorized root
first, reject absolute/parent-escaping relative names, reject unexpected symlink or
reparse-point traversal, and keep the final create under that authenticated root.
On platforms that support directory-relative no-follow opens, hosts should prefer
that mechanism over string-prefix checks. The host owns trusted parent traversal,
containing-directory sync, encryption,
quota/retention, revocation freshness, physical erasure, backup deletion,
independent witness storage and selection/rollback. File locks fence cooperative
independently opened handles, not hostile writers or cloned/inherited handles.
Platform and filesystem-specific creation, locking and power-loss behavior need
separate target-host qualification.

## Verification and non-claims

Regression coverage must include real-file reopen, every snapshot truncation
point, independent witness mismatch, canonical form, existing nonempty, empty and
truncate-to-zero rejection, regular and dangling symlink rejection where
supported, exactly one concurrent creator, lock contention, post-create
interference, payload integrity, revocation descendants and invalid binding.
Exact source and actual-base synthetic-merge compilation, tests, lint and format
remain mandatory.

This specification alone does not claim source implementation, execution,
independent acceptance or release. It adds no production caller,
selection, promotion, merge, filesystem credential or runtime authority. All
external evidence and release gates remain unchanged.
