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

Creation of the capability precedes semantic validation. A validation rejection
may leave a zero-length orphan. The host reconciles or separately removes that
orphan and must not reuse the path. Bytes appearing between atomic creation and
the guarded write return `Indeterminate`; lock contention returns `Busy`; a
write or sync error is also `Indeterminate`.

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

Atomic `create_new` closes the final-component existence-check/write race but
does not authenticate ancestor traversal, preserve a path-to-inode binding,
synchronize the containing directory or isolate hostile writers. The host still
authenticates target parents, witnesses and registry revocations; owns
parent-directory synchronization and cross-store reconciliation; and separately
authorizes use. File locking is not authentication or continuous revocation
freshness. Logical revocation is not physical erasure.

Required tests cover read-only loading, shared readers, writer lock contention,
transient duplicates, existing empty and truncate-to-zero targets, symlinks,
concurrent creators and post-create interference. Test source and CI submission
are not passed execution evidence; source-head, actual-base merge, product-matrix
and independent review gates remain mandatory. No capability or completion state
is advanced by this document.
