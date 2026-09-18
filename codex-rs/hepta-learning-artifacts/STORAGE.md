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
read_dataset_withdrawal_snapshot(File, DatasetWithdrawalSnapshotReceiptV1)
write_lifecycle_journal_snapshot(CreateOnlyArtifactFile, &ArtifactLifecycleJournalV2, Digest32)
read_lifecycle_journal_snapshot(File, LifecycleJournalSnapshotReceiptV2, replay_now)
CreateOnlyArtifactFile::create_in(parent, file_name)
remove_zero_length_orphan_in(parent, file_name)
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
model bytes are never executed. Artifact, withdrawal and lifecycle owner histories
share a 4096-record durable ceiling; canonical snapshot files are bounded by 8 MiB
and payloads by 64 MiB. Aligning the in-memory ceiling with supported durable
serialization prevents the owner from accepting record-count state that it cannot
later persist. Snapshot creation is O(history), bounded by the pilot cap; this is
not a high-frequency journal or hard-real-time controller.

The withdrawal and lifecycle adapters are independent create-only durable stores.
Their receipts bind the external scope binding, complete file digest, record count
and chain head; withdrawal receipts additionally bind the scoped withdrawal-domain
digest. Reload performs bounded reads, full semantic replay and canonical
re-encoding. The lifecycle V2 journal head commits producer identity plus the
full actor evidence tuple as well as the stable lifecycle-event digest, preventing
a replay from changing authorization semantics while retaining the same chain
head. Lifecycle reload reconstructs the persisted snapshot through historical
replay validation: recorded actor evidence is checked against the recorded event
time, not the restart wall clock; current-time credential validity remains
mandatory for new lifecycle mutations. These stores do not discover a
newest generation or grant publication authority by themselves.

## Failure and retry semantics

Validation occurs after the caller creates the opaque capability but before any
artifact bytes are written. Invalid binding, ineligible artifact or payload
mismatch therefore leaves a zero-length orphan for host reconciliation. It does
not authorize reusing that path: a second `create` must return
`AlreadyExists`.

For host-authorized flat namespaces, `CreateOnlyArtifactFile::create_in` rejects
lexical traversal, nested final names and a direct symlink parent before the final
`create_new`. `remove_zero_length_orphan_in` can reconcile only a zero-length
regular file under that same naming rule, after an exclusive cooperative lock and
a second length/type check. The host must independently prove that no successful
receipt references the path. Nonempty files, symlinks and directories are never
treated as orphans.

After successful atomic creation, a nonzero length observed before the guarded
write indicates interference and returns `Indeterminate`. Lock contention
returns `Busy` without this writer writing bytes. A write or synchronization
failure is `Indeterminate`; the caller must reconcile the exact target and
expected digest. It must never truncate, overwrite, silently adopt or retry
through the same path. Removal of a proven orphan is a separately authorized
host operation.

## Host transaction and trust boundary

The host authenticates the scope, target parent, file ownership, identities and
receipt. Digests and differing evaluator strings alone do not authenticate
people or services. A current external revocation witness is mandatory before
any runtime use: a valid old snapshot plus its old receipt can still predate a
deletion. This module cannot infer the latest state from the suspect file. Never
use an older snapshot to make a revoked predecessor appear eligible for rollback.

Create payload -> sync -> create canonical registry snapshot -> sync -> durably
publish the receipt/current-head witness -> acknowledge the producer/source ->
independent evaluation/decision -> separately owned next-run selection.

`ArtifactPublicationTransactionV1` makes that host transaction contract
executable without claiming impossible cross-file atomicity. It binds the V3
admission, scoped withdrawal frontier, artifact-registry namespace identity,
exact registry append, snapshot receipt and current-head witness. The V3-to-V1
projection preserves the exact dataset digest as V1 `support_digest` for a
dataset-derived artifact with one source dataset, while keeping the V1 event ID
equal to the exact host operation ID. The complete V3 admission frontier is bound
instead by a deterministic `snapshot_binding` over the operation, registry
namespace, admission/manifest, withdrawal frontier and exact registry append.
Both the durable registry snapshot receipt and current-head witness receipt must
carry that binding. The host must also retain/reconstruct the previous contract for
each operation ID and apply `validate_artifact_publication_retry_v1` (or an
equivalent durable operation-ledger rule), so identity reuse with changed semantics
conflicts instead of becoming a second publication interpretation. Multi-dataset or
multi-predecessor V2 manifests fail closed at this V1 bridge rather than losing
durable semantics. Recovery has only four phases:
`Prepared -> SnapshotDurable -> WitnessDurable -> Acknowledged`. A source
acknowledgement is forbidden before `WitnessDurable`. Two synced files are still
not a distributed transaction; restart requires the immutable publication contract
(or an authenticated deterministic reconstruction) plus durable receipts, verifies
the contract binding, and refuses to reinterpret snapshot-only state as published.

`create_new` protects the final path component from an existence-check race;
`create_in` additionally catches lexical escape and a direct symlink parent. These
APIs still do not retain an ancestor directory-handle binding against hostile
replacement, synchronize the parent directory or isolate hostile writers. The host
owns trusted parent traversal, containing-directory sync, encryption,
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
