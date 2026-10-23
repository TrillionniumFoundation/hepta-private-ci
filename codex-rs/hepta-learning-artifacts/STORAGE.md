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

The retained capability-based public writer signatures are:

```text
write_registry_snapshot(CreateOnlyArtifactFile, &ArtifactRegistry, Digest32)
write_candidate_payload(CreateOnlyArtifactFile, &ArtifactRegistry, &StableId, &[u8])
write_registry_head_witness(CreateOnlyArtifactFile, &RegistryHeadWitnessV1, &RegistryHeadRequirementV1, Digest32)
read_registry_head_witness(File, RegistryHeadWitnessReceipt, &RegistryHeadRequirementV1)
```

For new path-based host integration, prefer the contained validation-before-create
variants `write_registry_snapshot_beneath`, `write_candidate_payload_beneath`
and `write_registry_head_witness_beneath`. They accept a host-designated trusted
root plus a strictly relative path, reject absolute/parent/non-normal path
components and symlink ancestors, complete semantic validation first, then create
the final component with `create_new`.

Scoped withdrawal and lifecycle state also have canonical create-only adapters:
`write/read_dataset_withdrawal_snapshot` and
`write/read_artifact_lifecycle_snapshot`, plus contained `*_beneath` writers.
Their receipts bind file digest, byte count, record count and chain head;
withdrawal receipts additionally bind the withdrawal scope digest.

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
model bytes are never executed. Artifact-registry, withdrawal and lifecycle
state share `MAX_DURABLE_ARTIFACT_RECORDS = 4096`; this aligns the logical
record ceiling with the supported durable representation. V1 registry and
auxiliary snapshots are bounded at 8 MiB and candidate payloads at 64 MiB.
Snapshot creation/replay is O(history), bounded by the source cap; this is not a
high-frequency journal or hard-real-time controller.

## Failure and retry semantics

The retained low-level capability APIs allow the caller to create an opaque file
before a later semantic validation call. A rejected binding/manifest/payload on
that legacy path can therefore leave a zero-length orphan for host
reconciliation, and that path must never be reused.

The new contained high-level writers invert that order: they validate and encode
first, then create the final path. Ordinary semantic rejection therefore leaves
no final-path orphan. A failure after final-path creation is still treated as an
indeterminate write and requires reconciliation.

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

`ArtifactPublicationTransactionV1` is the hard host publication contract:
`Prepared -> PayloadDurable -> RegistryDurable -> WitnessDurable -> Acknowledged`.
It binds the complete scoped V3 admission to the exact V1 compatibility-registry
receipt and independently validated head-witness receipt. Acknowledgement before
witness durability is rejected, and replayed crash snapshots preserve their last
durable phase.

The named `LearningArtifactOwnerService::revoke` now drives an explicit v2
mutation in the **same** owner journal and writer fence. Its phases are
`Prepared -> RegistryDurable -> WitnessDurable -> Acknowledged`: a denial has
no new payload or fabricated admission. Original v1 publication checkpoint
bytes retain their format. The v2 checkpoint retains the complete `StateChange`,
signed-head digest, original writer-lease digest, scope and observed withdrawal
head, predecessor, immutable receipts and phase digest.

The writer lease must cover the original producer. The evaluator must equal
the independently trusted CURRENT signer and differ from the producer. The
request operation ID equals the signed registry event ID; CURRENT authenticates
the complete resulting registry head, including artifact, evaluator and reason.
The original registry enforces irreversible revocation and descendant
ineligibility. Installing a newer in-memory dataset withdrawal frontier alone
does not claim that a registry Revoke was published.

Exact retries use the original checkpoint and reestablish ACK durability before
returning its receipt. A failed write or sync after a checkpoint leaves the
service recovery-required: authenticated CURRENT reads and unrelated mutations
are blocked until exact reconciliation or a durable reopen. Restart should use
the independently retained signed current-head floor; a restored older local
snapshot cannot override that floor. Neither revocation nor an ACK permits
physical erasure or restores an ancestor's eligibility.

The service acquires `writer/current-observation.lock` after its writer fence
and before reconciliation or publication. It releases that observation lock
only after a known terminal result and retains it across an uncertain ACK and
exact retries. Independent CURRENT observers use this same observation boundary
without acquiring the writer lease; a live uncertain writer prevents them from
turning readable bytes into an acknowledged observation.

`ArtifactOwnerCurrentReaderV1` supports Linux and macOS, where regular-file opens
use nonblocking/no-follow flags and verify the pinned file identity. It returns
`UnsupportedObservationPlatform` before opening the store on Windows and other
Unix ports. The original named writer retains its existing platform behavior;
Windows writer behavior was not exercised in this campaign. The observation
lock must remain the same inode. Older writer binaries that do not take this
fence must not run alongside this reader against the same store. Public host
mutation entrypoints are now crate-private: embedding publishers must use the
named service, which owns the complete observation-lock transaction lifetime.
Public host diagnostic reads authenticate signed head/snapshot bytes and do not
establish service uncertainty clearance.

The reader's 250 ms bound applies to lock acquisition. Complete ACK revalidation,
file and directory synchronization and bounded history scanning occur while
holding the lock and can take longer on slow storage. Reader failure or prolonged
writer contention requires explicit consumer reload; an old view cannot restore
a closed cache. This consistent-view protocol does not replace the runtime's
separate final-use and external-effect fences.

On Unix the named host now synchronizes parent directory entries for new
directories and existing directory chains on reopen, checkpoints and signed
heads, and synchronizes both file and parent for payload, registry and witness
publication or exact-file retry. A sync error
remains `Indeterminate`. This is an implemented filesystem protocol, not a
power-loss qualification receipt. Windows directory-entry durability is still
unqualified; file synchronization does not establish equivalent guarantees.

This remains an ordered host durability protocol, not a cross-file atomic
filesystem transaction. The host must durably persist each transaction snapshot
under its writer fence before treating the phase as durable. A crash before
witness publication may leave durable bytes or a registry generation, but never
a valid acknowledged publication.

`create_new` protects the final path component from an existence-check race.
`create_beneath_trusted_root` additionally rejects lexical escape and symlink
ancestors under a canonical trusted root. Neither API is an `openat2`-style
directory capability: the host must prevent concurrent hostile replacement of
trusted ancestors and still owns containing-directory sync, encryption,
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

The named service implements publication and denial through the existing owner;
its receipts retain `DENY_ALL` authority. This documentation and local source
tests do not establish independent acceptance or deployment qualification, and
grant no selection, promotion, merge, filesystem credential or runtime authority.
External evidence and release gates remain unchanged.
