# ui.native technical development guide

**Module:** `ui.native`  
**Owner / deputy:** `ui-platform` / `accessibility`  
**Canonical branch:** `work/ui-native-qualified-integration-20260928`  
**Convergence branch:** `work/ui-native-product-closure-20260930`  
**Immutable implementation source:** `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52`  
**Implementation tree:** `136c62bfe0cc0ca6c7455169162c3f5a1b951f8a`

This source is an implementation candidate. It is not production-qualified,
deployment-qualified or release-authorized. The product source is frozen at the
commit and tree above; later commits may change only qualification code,
evidence metadata and review navigation. A formatter output is source and must
be committed before the candidate is re-frozen.

Read `CURRENT_SOURCE.json`, `CURRENT_DELIVERY.json`,
`IMPLEMENTATION_MAP.json`, `QUALIFICATION_MANIFEST.json` and `REVIEW_DIFF.md`
together. Missing, cancelled, skipped, dirty, stale-SHA, foreign-parent,
modified-package or over-budget evidence is failure. Source code and unexecuted
tests are not passing receipts.

## 1. Mission, ownership and claim boundary

The module provides native desktop presentation, authenticated runtime reads,
bounded local platform operations, durable operation observations and signed
update coordination. It does not mint final-use grants, create a second runtime
truth store, select releases or own deployment policy.

`NativeShellRuntime` is the single runtime and journal owner. The gateway owns
authenticated read transport. The kernel final-use owner retains nonce,
epoch, expiry and revocation authority. Platform policy is an additional ceiling,
not a replacement for authority. UI lanes, picker callbacks, retirement indexes,
SBOMs and qualification fixtures never become execution authority.

Current state is:

```text
implementation-candidate / qualification-blocked / release-not-authorized
```

## 2. Immutable ordinary-source history

The convergence chain is a normal Git history:

1. canonical base `6f145464d9d58233c59aafe262a1250a5ea873a8`;
2. ordinary WAL/index source, including `4bc29cf124dc5532d04349e478bc82f5d4959fd9`;
3. Linux portal/resource boundary `23d20707aebcdf8e5646d2bc3d74fd6751ec83d9`;
4. UI lane split and durable paging `172fb1edaa5471c7cb28e14582c2b2a2dc1ff6f3`;
5. closed unsigned package inventory `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52`.

Patch capsules, apply-once workflows and CI-created product commits are not
source delivery. The sole module workflow has `contents: read`, checks explicit
SHAs and never applies, commits or pushes source.

## 3. Internal architecture

`main.rs` composes endpoint trust, keyring, policy, journal, final-use gate,
updater and GUI. `backend.rs` and `native_http.rs` implement authenticated
loopback reads. `security.rs` binds an exact displayed view, payload and optional
resource identity to the final-use owner.

`journal.rs` owns the active operation state machine and exact
`HashMap<OperationKey, usize>` lookup. `journal_storage.rs` owns snapshots and
framed WAL persistence. `retirement.rs` owns immutable segments, archived
receipts and a rebuildable disk index. `private_state.rs` rejects unsafe roots,
redirects and permissions.

The GUI has three supervised lanes:

- one mutation-owner lane for runtime, journal, update and readiness mutation;
- one bounded read lane for persistent operation-history pages;
- one platform-picker lane for an owned native dialog.

Read and mutation admission are mutually exclusive under the same runtime owner.
The picker does not own runtime state. Shutdown attempts cancellation only before
admission and joins all lanes before update activation.

## 4. Journal, WAL and checkpoint protocol

The active writer uses `hepta.native-operation-journal.v7`. Every state-changing
upsert appends one framed `hepta.native-operation-wal.v1` entry with monotonic
sequence, previous-entry checksum, complete validated record and entry checksum.
The frame has fixed magic, bounded length and payload SHA-256. The file is
synchronized before memory changes.

Checkpoint order is:

1. validate active records and retirement checkpoint;
2. serialize a checksummed v7 snapshot with WAL frontier;
3. preserve the prior snapshot as forensic evidence, never automatic replay;
4. atomically replace and synchronize snapshot and parent directory;
5. only then truncate and synchronize the WAL.

Open validates the private root, snapshot, retirement checkpoint and complete WAL
chain under one lock. A final incomplete frame may be truncated to the last
verified boundary. Bad magic, invalid length, checksum mismatch, sequence gap,
previous-checksum mismatch, illegal transition or record conflict fails closed.
After persistence error the owner is fenced; reopen and reconcile instead of
retrying through the same object.

## 5. Retirement authority and acceleration

Immutable retirement segments and content-addressed archived receipts are the
audit authority. `hepta.native-retirement.v3` publishes a checkpoint-bound
`hepta.native-retirement-index.v1` manifest whose bounded buckets map exact
identity digests to optional receipt digests. Manifests, buckets and caches are
rebuildable acceleration only.

Index uncertainty may reject work or trigger deterministic rebuild, but it must
never make a retired identity executable. Segment and record publication precede
the indexed head. A regressed or unrelated checkpoint is rejected. The local
chain detects corruption and partial rollback; it is not an external anti-rollback
authority if every local file is restored consistently.

## 6. Final-use and platform effect protocol

The effect order is:

```text
immutable request validation
→ adapter confirmation resource
→ durable Prepared
→ local permission
→ final-use claim/current revalidation
→ durable Invoking
→ final local policy and verified-use fence
→ platform boundary
→ durable terminal or Indeterminate observation
```

An exact duplicate is a read, not another effect. Reuse with changed endpoint,
session, subject, revision, action, payload, binding or grant is a conflict.
Once the OS boundary may have been crossed, errors remain uncertain unless an
operation-bound trustworthy observer resolves them. UNKNOWN is never
automatically replayed.

Clipboard success requires exact immediate readback. Notification launcher exit
never proves delivery. Notification and external-open results therefore remain
`Indeterminate` unless a queryable operation-bound receipt is available.

## 7. Linux verified resource handoff

Linux `OpenPath` and `RevealPath` no longer reopen a mutable path after final-use
admission. The adapter:

1. requires an absolute path inside the canonical policy root;
2. opens it with `NOFOLLOW` and retains the descriptor;
3. accepts only a regular file or directory;
4. verifies the open descriptor still resolves beneath an allowed root;
5. hashes device, inode, mode, size, mtime and ctime into the confirmation
   resource identity;
6. reopens and revalidates the exact identity at final effect entry;
7. passes the already-open descriptor to XDG OpenURI using a Unix FD list.

A changed identity fails before handoff. A final symlink is rejected. The portal
response is a submission observation, not proof that an external application
completed the requested effect. Non-Linux Open/Reveal remains fail-closed until
an equivalent verified resource-capability adapter is implemented and qualified.

## 8. Native file input

Each grant, update manifest or package selection is armed with an exact target
and monotonic ticket. A stale callback, screen change, cancellation or target
replacement cannot populate another field. Drag/drop uses the same target
binding. A selected path is untrusted input and is reopened through the bounded
regular-file reader.

Linux is XDG Desktop Portal-first. The static adapter subscribes to the expected
request object before `OpenFile`, uses a bounded handle token, accepts one local
`file://` URI, requires strict UTF-8 and an absolute path, and closes on timeout.
`HEPTA_NATIVE_PICKER_BACKEND=zenity` selects the explicit compatibility backend;
there is no ambient automatic fallback. macOS uses absolute
`/usr/bin/osascript`; Windows uses an absolute system PowerShell/OpenFileDialog
adapter. Child environments are cleared and only required desktop/session values
are reintroduced.

## 9. Windows packaged identity and notification

The deterministic unsigned Windows package contains
`Register-HeptaNativeIdentity.ps1`. It creates a per-user Start Menu shortcut,
commits `Trillionnium.Hepta.Native` through `IPropertyStore`, and writes the local
identity marker only after shortcut and property-store commits succeed.

The WinRT toast adapter requires that marker and uses the exact registered AUMID.
The source and package inventory are implemented, but successful registration,
shortcut property verification and visible toast behavior require a packaged
physical Windows qualification run. Their presence in source is not execution,
signing or release evidence.

## 10. Persistent history and UI concurrency

`operation_history_page` returns one newest-first page directly from the journal
slice. Page size is bounded to 256 and the GUI uses 64 receipts. The UI no longer
copies the complete active history after refresh, reconcile or execution.
Compaction remains an owner mutation and archives complete records before active
removal.

The picker lane may remain open without blocking refresh or reconciliation. The
read lane and mutation lane never run concurrently, preserving one journal and
runtime authority. Shutdown cancels waiting tasks, waits for admitted tasks and
only permits update activation after every lane and runtime close are confirmed.

## 11. Performance and hard budgets

Blocking provisional ceilings live in `apps/hepta-native/STORAGE_BUDGETS.json`:
4096 active records, one million retired identities, bounded WAL/snapshot bytes,
mutation p50/p95/p99, cold-start p95, peak RSS, deterministic index rebuild,
write amplification and bounded history paging.

The exact-source storage job runs both ignored qualification subjects on Linux.
The active subject measures 12,288 state transitions, cold reopen, snapshot, WAL
and peak RSS. `strace -ff -yy` records successful write/pwrite and
fsync/fdatasync calls whose descriptors resolve inside the qualification root.
The retirement subject builds one million exact identities, verifies indexed
cold open and requires deterministic legacy-index rebuild.

Declared budgets remain `provisional-unqualified` until the immutable workflow
artifact passes every ceiling and is independently reviewed.

## 12. Qualification and supply-chain evidence

The read-only workflow evaluates exact head and a deterministic ordered-parent
merge on Linux, macOS and Windows. It runs source identity, Rust 1.95 formatting,
all-target/all-feature check, strict Clippy, native and owner tests,
compiler-negative boundaries, process-kill and updater rollback, deterministic
unsigned packaging and packaged fault qualification. Linux also runs the real
gateway/keyring/Xvfb lifecycle and exact-source storage scale.

Each platform subject emits:

- complete check logs and exact source identity;
- deterministic package receipt and archive digest;
- CycloneDX 1.6 SBOM generated from both Cargo lockfiles;
- SLSA-shaped in-toto provenance binding candidate, ordered base, exact/merge
  subject, implementation source, runner and package digest.

The aggregate revalidates all six bundles and binds their supply-chain digests.
SBOM and provenance generation is repository-controlled evidence only. It does
not establish production signing, notarization, Authenticode, physical-host
acceptance or release authorization.

## 13. Remaining gates

The source-side convergence is implemented, pending compilation and execution.
Promotion still requires:

- one successful seven-subject run against one immutable candidate;
- every 4096/1,000,000 storage ceiling passing;
- measured source coverage and sustained soak;
- physical Windows, macOS, X11 and Wayland acceptance;
- multi-display, mixed-DPI, Chinese IME, screen-reader and keyboard acceptance;
- physical packaged Windows AUMID and WinRT notification verification;
- Developer ID/notarization, Authenticode, Linux repository signing and key
  custody/revocation evidence;
- independent SBOM/provenance acceptance;
- independent promotion review and application of branch protection by a
  repository administrator.

Until those gates close, `productionQualified`, `deploymentQualified` and
`releaseAuthorized` remain false.
