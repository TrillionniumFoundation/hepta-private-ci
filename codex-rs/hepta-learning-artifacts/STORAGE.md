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

Preferred new-host flow validates before creating the final path:

```text
prepare_registry_snapshot_v1(&ArtifactRegistry, Digest32)
write_prepared_registry_snapshot_v1(CreateOnlyArtifactFile, PreparedRegistrySnapshotV1)
prepare_candidate_payload_v1(&ArtifactRegistry, &StableId, &[u8])
write_prepared_candidate_payload_v1(CreateOnlyArtifactFile, PreparedCandidatePayloadV1)
prepare_registry_head_witness_v1(&RegistryHeadWitnessV1, &RegistryHeadRequirementV1, Digest32)
write_prepared_registry_head_witness_v1(CreateOnlyArtifactFile, PreparedRegistryHeadWitnessV1)
```

The original one-shot `write_registry_snapshot`, `write_candidate_payload` and
`write_registry_head_witness` APIs remain compatibility wrappers. Hosts that
control a root directory may use `CreateOnlyArtifactFile::create_in(root, relative)`
to reject absolute paths, parent traversal and symlinked ancestor escapes before
final-component creation. `ArtifactStorageAdminV1::enroll` exposes the same
canonical-root discipline for inspection and deliberately narrow orphan cleanup.

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
model bytes are never executed. The in-memory artifact registry, withdrawal
registry and lifecycle journal share the same 4096 durable-record cap, so an
owner mutation cannot exceed what canonical persistence can represent. Artifact
and control snapshots are bounded by 8 MiB; payloads are bounded by 64 MiB.
Snapshot creation is O(history) within the pilot cap; this is not a high-frequency
journal or hard-real-time controller.

## Failure and retry semantics

The compatibility one-shot writers receive an already-created capability, so a
semantic rejection can still leave a zero-length orphan. New hosts should call
the prepare API first and create the final path only after prepare succeeds;
invalid binding, ineligible artifact, payload mismatch or stale witness then
creates no final-path orphan. Once creation/write begins, failure can still leave
a zero-length or partial orphan for host reconciliation. No failure authorizes
reusing that path: a second `create` must return `AlreadyExists`.

After successful atomic creation, a nonzero length observed before the guarded
write indicates interference and returns `Indeterminate`. Lock contention
returns `Busy` without this writer writing bytes. A write or synchronization
failure is `Indeterminate`; the caller must reconcile the exact target and
expected digest. It must never truncate, overwrite, silently adopt or retry
through the same path. Removal of a proven orphan remains separately authorized by the host.
`ArtifactStorageAdminV1::cleanup_zero_length_orphan` is the crate-owned safe
mechanism for that operation: it removes only a zero-length regular file below
an enrolled canonical root, refuses symlinks/non-empty/special entries, and
syncs the containing directory after deletion.

## Host transaction and trust boundary

The host authenticates the scope, target parent, file ownership, identities and
receipt. Digests and differing evaluator strings alone do not authenticate
people or services. A current external revocation witness is mandatory before
any runtime use: a valid old snapshot plus its old receipt can still predate a
deletion. This module cannot infer the latest state from the suspect file. Never
use an older snapshot to make a revoked predecessor appear eligible for rollback.

Create payload -> sync -> create canonical registry snapshot -> sync -> durably
publish the receipt/witness -> independent evaluation/decision -> separately
owned next-run selection. Cross-store atomicity requires a host transaction or
outbox reconciliation; two synced files are not an atomic multi-store transaction.
A crash before witness publication may leave an orphan candidate, not a selected
artifact.

`create_new` protects the final path component from an existence-check race.
`create_in` additionally canonicalizes a host-selected root and target parent and
rejects lexical traversal or symlink-parent escape. It still cannot retain a
path-to-inode binding against a hostile rename race, synchronize the parent
directory for ordinary writes or isolate hostile writers. Orphan cleanup does
sync its containing directory after a successful removal, but that does not
upgrade ordinary publication into a hostile-filesystem proof. The host owns target-host openat-style
containment where required, containing-directory sync, encryption,
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
interference, payload integrity, revocation descendants, invalid binding, parent-escape
rejection and zero-length-only orphan cleanup.
Exact source and actual-base synthetic-merge compilation, tests, lint and format
remain mandatory.

This specification alone does not claim source implementation, execution,
independent acceptance or release. It adds no production caller,
selection, promotion, merge, filesystem credential or runtime authority. All
external evidence and release gates remain unchanged.
