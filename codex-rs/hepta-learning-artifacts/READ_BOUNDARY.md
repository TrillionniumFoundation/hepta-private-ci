# Artifact file reader and writer boundary

This ART-1/ART-2 hardening preserves immutable snapshot and payload formats,
manifests, lineage validation, content digests, quotas and read behavior. It
specifies an enforceable create-only writer boundary and adds no selection or
installation operation.

## Writer capability

`CreateOnlyArtifactFile` is an opaque one-shot capability. The module is its
only safe constructor and creates the authorized final path component atomically
with `OpenOptions::create_new(true)`. On Unix the requested creation mode is
`0600`, subject to a stricter umask. An existing nonempty file, existing empty
file, acknowledged file truncated to zero, regular symlink or dangling symlink
must all fail creation with `AlreadyExists`; no existing inode is opened for
writing.

`write_registry_snapshot` and `write_candidate_payload` consume this
capability. There is no `From<File>`, dereference, raw-handle conversion, clone
or extraction surface. Consequently an arbitrary writable `File` cannot be
promoted to create-only authority. The implementation retains an exclusive
advisory lock while checking the new file is still empty, writing and calling
`sync_all`.

The retained low-level capability path still permits creation before semantic
validation, so a rejected legacy write may leave a zero-length orphan that the
host must reconcile and never reuse.

New integrations should prefer the `*_beneath` high-level writers. They perform
semantic validation and canonical encoding before the final path exists, then
call `CreateOnlyArtifactFile::create_beneath_trusted_root`. Invalid binding,
ineligible artifact, payload mismatch, invalid witness or unscoped withdrawal
state therefore leaves no final-path validation orphan. Bytes appearing after
creation but before the guarded write return `Indeterminate`; lock contention
returns `Busy`; a write or sync error is also `Indeterminate`.

## Reader capability and locks

`read_registry_snapshot` and `read_candidate_payload` continue to accept
independently opened OS read-only `File` values and acquire shared locks. A
consumer does not need write access to load a witnessed registry or eligible
artifact.

A private owned-file guard is created only after lock acquisition succeeds. It
explicitly unlocks on normal success or rejection before closing the file. This
prevents a transient inherited open description from retaining a completed
operation's lock. Failure to acquire a lock never unlocks another owner. The
bounded reader borrows the file for `Read::take` so ownership cannot escape the
guard. Caller-supplied already locked or concurrently used aliases remain
unsupported; duplicate handles appear only in regression fixtures.

## Trust boundary and evidence

Atomic `create_new` closes the final-component existence-check/write race.
`create_beneath_trusted_root` additionally rejects absolute/parent/non-normal
relative paths and symlink ancestors below a canonical host-designated root.
This is not a substitute for an OS directory-handle primitive such as
`openat2`: the host still prevents concurrent hostile ancestor replacement,
authenticates the trusted root, witnesses and registry revocations, owns
parent-directory synchronization and cross-store reconciliation, and separately
authorizes use. File locking is not authentication or continuous revocation
freshness. Logical revocation is not physical erasure.

Required tests cover read-only loading, shared readers, writer lock contention,
transient duplicates, existing empty and truncate-to-zero targets, symlinks,
concurrent creators and post-create interference. Test source and CI submission
are not passed execution evidence; source-head, actual-base merge, product-matrix
and independent review gates remain mandatory. No capability or completion state
is advanced by this document.


## Scoped durable state

The same create-only and bounded-read trust model now applies to
`DatasetWithdrawalRegistry` and `ArtifactLifecycleJournalV2` through
`durable_snapshots.rs`. Withdrawal recovery binds the independently retained
scope digest as well as the chain head and file digest. Lifecycle recovery
replays actor evidence at each immutable event's `occurred_at`, so later
credential expiry cannot make valid history unreadable while a new post-expiry
mutation still fails.

`admission_storage.rs` extends this boundary to complete `HEPTAA03` sidecars.
Their 128 KiB ceiling and collection counts are checked before decoding
allocations; semantic pins and canonical re-encoding cover all V2 provenance and
expiry fields. Strict CURRENT verification joins those sidecars to the witnessed
V1 registry and authenticated scoped withdrawal frontier. Legacy V1-only reads
retain their narrower compatibility contract and cannot replace a strict view
after that mode has been established. See `PINNED_LOAD.md` and
`DATASET_REVOCATION.md` for exact backfill and use-time eligibility.

## Plasticity compatibility limit

The built-in file CURRENT adapter proves only the signed V1 frozen projection.
It does not supply sidecars or a live authenticated withdrawal frontier. A strict
provider remains necessary for full-provenance consumption. Once a strict view is
supplied, frozen plasticity verifies the exact use time and every initially
eligible frozen artifact, and refuses a later V1 downgrade. A failed refresh is
latched by the runtime until explicit generation rebootstrap. This guard does not
make the V1 file adapter a strict provider or create installation authority.
