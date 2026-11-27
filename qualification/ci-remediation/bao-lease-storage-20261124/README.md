# Bao lease registry durability repair

## Observed failure and source cause

The original #6995 Windows shard 2 log (4,056,055 bytes, SHA-256
`bf49ce6af4b1c7fef8288517872f8e335db9d678eebd05097cfced9deebdf49f`)
contains seven lease lifecycle failures at the first durable mutation. The old
publisher opened the containing directory with ordinary `File::open`, which
is not a Windows directory handle with the access needed for a real flush.
The old owner also retained and continued using its cached state after a
publication I/O error, even if a rename had already changed the disk state.

Source implementation: `e9c9ad7782f736cde0981c0c6a18f5212cfa93cb`.

## Resulting behavior

Windows now retains `PrivateDirectory`, including the existing same-handle
owner-only protected ACL, local NTFS, hard-link and reparse checks. It creates
or validates the private containing directory, opens validated single-leaf
files relative to that handle, flushes the complete staged file, replaces the
name with the native rename operation, and performs the real directory flush.
Unsafe existing objects are rejected without ACL repair. Existing inherited
or broader Windows directories must be provisioned privately by the owner;
opening the registry does not silently migrate their permissions.

Any publication I/O failure poisons that registry instance. Cached getters no
longer expose the earlier state and every transition, including duplicate
prepare and a no-change expiry scan, returns `Unavailable`. A fresh open is
required to read and validate actual persisted state. This conservative fence
also covers errors that occur before rename; it does not claim to identify a
particular power-loss outcome. Unix publication keeps its existing mechanism.

Serialization now checks the same 8 MiB ceiling used by the reader before
writing anything. An oversized proposal returns `CapacityExceeded`, preserves
the existing file and leaves the earlier owner usable.

Fixtures use a new private child directory beneath their temporary root so
that Windows exercises real private directory creation. No lifecycle assertion
is removed. New tests cover failed publication and reopen, the reader/writer
capacity boundary, inherited-ACL rejection and hard-linked staging rejection.

## Measured validation and limits

An isolated manifest compiled the actual repository `lease_lifecycle.rs` and
its real sibling storage/test modules, without copying their implementation or
mocking filesystem operations. Its relevant serde, serde_json, tempfile and
native windows-sys versions match the workspace lock. The first eight Linux
tests passed with zero skips; after the capacity case was added, that selected
case passed (the previously executed eight were filtered out). There are nine
distinct Linux test cases with actual execution receipts. Two initial harness
configuration attempts stopped before compilation because the standalone
manifest did not define the repository's nextest `local` profile and could not
resolve unrelated workspace package filters; neither is a test result. The
final standalone profile keeps a 60-second watchdog, one test thread and zero
retries.

Actual Windows-target source, including the two additional Windows tests and
the revised native directory flags, passed Rust 1.96 MSVC `cargo check --tests`.
That is compilation only. The native Windows lane must execute all eleven
lifecycle tests and the separate `PrivateDirectory` tests. No Windows runtime,
full workspace, final dependency graph, or power-loss qualification is claimed.
Scoped `just fix` on the actual-source harness completed without warnings or
source edits. Repository `just fmt` and handwritten diff checks passed.

`receipt.json` binds the source and logs. The full combined Cargo/Bazel locks
are generated on the integration branch. The normal Windows workflow must execute
the lease lifecycle selector; its exact new-head result remains the acceptance
gate.

Native API references: [Directory handles](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory), [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers), and [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile).
