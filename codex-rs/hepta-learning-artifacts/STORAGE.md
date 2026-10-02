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

## Complete V3 admission sidecars

`admission_storage.rs` adds `HEPTAA03` without changing `HEPTAR01`, `HEPTAH01`
or payload bytes. Its public surfaces are:

```text
admission_snapshot_receipt_v3(&WithdrawalBoundArtifactAdmissionV3, binding)
write_artifact_admission_snapshot_beneath(root, relative, &admission, binding)
read_artifact_admission_snapshot(File, ArtifactAdmissionSnapshotReceiptV3)
read_artifact_admission_snapshot_bound(File, binding, scope, manifest_digest, admission_digest)
validate_admission_registry_projection_v3(&ArtifactManifest, &admission)
```

The owner names a sidecar `admissions/{manifest_digest}.admission`. The canonical
newline-terminated encoding stores the binding; withdrawal scope/head;
admitted-at time; admission/manifest digests; artifact/kind/generation/provenance;
counted dataset, lineage and predecessor lists; an explicit optional rollback
tag; all payload/training/runtime/device/objective/compatibility/schema/
normalization fields; producer; creation/expiry times; and `DENY_ALL`.
It rejects additional fields, alternate numeric/newline encodings, unordered or
duplicate closure inputs and authority escalation. A 128 KiB total limit,
128-byte field-line limit and the V2 64/1,024/64 collection ceilings bound parsing
and allocation before semantic replay.

`ArtifactAdmissionSnapshotReceiptV3` binds storage binding, withdrawal scope,
manifest digest, admission digest, file digest and encoded byte count. A bound
reader obtains its four semantic pins from the independently witnessed registry,
original registration checkpoint and owner scope. It verifies the whole semantic
digest and canonical bytes before returning a new file receipt. The observed file
length controls the read budget only. Deriving trusted pins from suspect bytes
remains forbidden.

Sidecar recovery checks historical validity at `admitted_at`; final publication
and runtime use check expiry and the live withdrawal frontier separately. Sidecar
writes validate before creation. Existing bytes return `AlreadyExists`; the
owner may only read/verify the exact expected evidence and synchronize the file
and containing directory before advancing its checkpoint. A different admission
for the same manifest path is a conflict, never permission to overwrite it.

V1-only files remain readable through compatibility APIs. A strict CURRENT reader
requires every sidecar and exact projection. Missing historical evidence requires
`LearningArtifactOwnerHost::backfill_artifact_admission` with the original trusted
admission and matching registration checkpoint. It cannot be fabricated from a V1
support digest or inferred as dataset-independent provenance.

## V1 snapshot and payload encoding

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

This remains an ordered host durability protocol, not a cross-file atomic
filesystem transaction. The host must durably persist each transaction snapshot
under its writer fence before treating the phase as durable. A crash before
witness publication may leave durable bytes or a registry generation, but never
a valid acknowledged publication.

The named owner implementation also publishes restrictions and withdrawal
frontiers through the separate `owner_state.rs` / `owner_state_storage.rs` saga:
`Prepared -> SnapshotsDurable -> WitnessDurable -> Acknowledged`. Registry and
scoped withdrawal snapshots are durable before signed CURRENT and terminal
acknowledgement. Recovery preserves the exact operation, predecessor floors,
receipts and original lease, and fences unrelated writes until reconciliation.
The new saga is additive; it does not reinterpret a V1 artifact-publication
checkpoint as a restriction checkpoint.

`LearningArtifactOwnerService::open_v2` requires the inner V1 owner configuration
and an independent `required_withdrawal_head_digest` in
`LearningArtifactOwnerServiceConfigV2`. Restart proves that withdrawal floor as
well as the independent CURRENT floor; a same-directory restored history is not
a source for either trusted floor. The compatibility
`install_withdrawal_frontier` accepts only an identical no-op. An advancement
must use `prepare_state_registry` and `publish_state` or returns
`DurableStatePublicationRequired`.

The externally trusted head signer also signs
`LearningArtifactStatePublishRequestV1::authorization_signing_bytes()` within
its explicit authorization interval. This domain-separated signature covers
the full state intent and next withdrawal frontier, including a no-op registry
delta whose signed CURRENT head is unchanged. Current requests check expiry;
historical checkpoint replay checks the original authorized-at time.

On Unix, the native owner synchronizes the root directory layout at startup and
each file's containing directory after writes and exact reconciliation. Direct
low-level adapters retain the caller's directory-sync obligation. Other targets
require the selected platform's directory-durability implementation and execution
qualification. This does not change trusted-path or restart-floor inputs.

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

This specification alone does not claim source implementation, execution,
independent acceptance or release. It adds no production caller,
selection, promotion, merge, filesystem credential or runtime authority. All
external evidence and release gates remain unchanged.

## Admission/recovery hardening

A host-local admission mutex complements the OS lifetime fence. New publications
must name actual CURRENT, and no second unfinished artifact/state operation is
accepted. Every resumed durability claim revalidates payload bytes and, for later
phases, exact registry/admission and witness bytes before another effect. The
protocol also binds every projected manifest field, canonical operation event ID,
and complete registry/witness byte receipts. Terminal service retries remain
historical acknowledgements, not evidence that retained payload bytes still exist.

Namespace reservations, orphan counting, supported limits and the distinction
between count budgets and real free space are documented in the technical guide,
Section 10. The early checkpoint still requires the externally retained exact
request. A partial immutable final file is not silently overwritten or repaired.
