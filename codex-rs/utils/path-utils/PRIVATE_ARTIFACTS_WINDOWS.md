# Retained private artifacts on Windows

## Component and callers

`private_artifacts_windows` provides `RetainedPrivateDirectory` and `PrivateFile`.
The private identity, security and native directory modules support these types.
This component is additive: existing State, Operator, Shadow and AuthBus callers
retain their current implementations. In particular, the generic sidecar lock
does not implement AuthBus's payload-bound lease or explicit stale-lock recovery.

The existing `private_state_windows` APIs remain available, including exclusive
directory and child creation. Only their existing private creation descriptor
helper is shared inside `codex-utils-path`; its owner and DACL policy is unchanged.

## Contract

`WindowsFileId` holds a volume serial and all 16 immutable file-ID bytes.
`PrivateFileIdentity` also records kind, link count, allocation, length,
timestamps, attributes and the validated owner/DACL descriptor. Inspection of a
borrowed `File` grants no additional write capability.

`RetainedPrivateDirectory::open_existing` requires a canonical absolute fixed
local NTFS path. It retains the ancestors and directory, rejects reparse objects
and replacement aliases, and obtains a real read/write directory handle. It
checks the full identity and private security before and after child operations.
Existing ownership and ACLs are never repaired or adopted as private.

`create_new` creates one absent leaf with the current-user owner and protected
inheritable DACL applied atomically. It verifies the created object and retained
ancestry, and flushes the original parent before acknowledging creation.

Private inspection preserves the effective-token owner policy and the explicit
System/Administrators boundary. Foreign nonzero allow ACEs, null or invalid
DACLs, unrecognized ACEs and malformed SID spans are refused. CreatorOwner is
accepted only as an inherit-only template. Files must be ordinary, non-reparse
objects with one hard link. Immutable reads retain full metadata equality;
directory mutations retain identity and security while allowing the expected
child-list timestamps to change.

Child names are checked single UTF-16 components. New files are exclusively
created relative to the retained directory with their private descriptor,
verified against exact written bytes, flushed, and followed by a real directory
flush. Replacement uses a distinct new sibling and a handle-relative rename.
Partial effects remain failures; no implicit cleanup or replay claims success.

`PrivateFile` exposes bounded reads, verification and real sync requests, without
exporting a raw handle or writable `File`. Read-only construction cannot produce
a writable directory. Sidecar handles exclude concurrent writers and deletion
until dropped; qualified existing sidecars can be locked again. Callers requiring
different lease, deletion or SQLite sharing semantics need a separate adapter.

## Verification

The existing Windows original-regression workflow runs all nine named backend
controls in a separate native job with pinned Rust, just and nextest versions,
zero retries, exact clean source checks and retained failure evidence. Its
collector rejects duplicate, missing, unexpected, wrong-package or nonpassing
terminal results. The existing 19 groups / 175 original cases and their aggregate
remain independent requirements.

The junction fixture invokes `cmd.exe` with a fixed complete command tail and an
explicit working directory. Only fixed child names enter the command grammar.
It verifies the created reparse object and its target before testing rejection;
the original refusal, unchanged-target and no-child-effect checks remain.

Run native tests with `just test --locked -p codex-utils-path --lib`. Use the
workflow collector for the exact nine-case receipt. A Linux build, cross check
or receipt-parser unit test does not establish native Windows durability.
Dependency changes require the repository-root `just bazel-lock-update`, even
when the generated module lock remains unchanged. Component results alone do not
qualify product callers, sandbox isolation or physical power-loss behavior.
