# ui.native technical development guide

**Module:** `ui.native`
**Owner / deputy:** `ui-platform` / `accessibility`
**Canonical branch:** `work/ui-native-qualified-integration-20260928`
**Convergence branch:** `work/ui-native-adversarial-audit-20261001`
**Immutable implementation source:** `ed5fd2229502099addd6bedec2fae18783d5c162`
**Implementation tree:** `4641d2abbf7db038404863b2f6a7975c28977fe1`

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
5. historical closed unsigned package inventory `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52`;
6. audit base `9be52d267d02a76f73e8a94fd086191c351d1c70`;
7. adversarial audit source `ed5fd2229502099addd6bedec2fae18783d5c162` (this immutable candidate).

Patch capsules, apply-once workflows and CI-created product commits are not
source delivery. The sole module workflow has `contents: read`, checks explicit
SHAs and never applies, commits or pushes source.

## 3. Internal architecture

`main.rs` composes endpoint trust, keyring, policy, journal, final-use gate,
updater and GUI. `backend.rs` and `native_http.rs` implement authenticated
loopback reads. `security.rs` binds an exact displayed view, payload and optional
resource identity to the final-use owner.

`codex-rs/utils/private-state` owns reusable Windows ACL, handle identity and
durable replacement primitives. Shared contracts depend directly on this
utility; `hepta-private-state` remains a compatibility export for the native
application. Domain authority stays with the calling owner. This avoids a
shared-contract dependency on a product module while preserving OS behavior.

`journal.rs` owns the active operation state machine and exact
`HashMap<OperationKey, usize>` lookup. `journal_storage.rs` owns snapshots and
framed WAL persistence. `retirement.rs` owns immutable segments, archived
receipts and a rebuildable disk index. `private_state.rs` retains directory identity and rejects unsafe roots,
redirects and permissions. Unix journal reads and mutations use the pinned
directory descriptor; atomic replacement verifies its parent descriptor and
synchronizes that same directory. Operator-selected ancestry remains trusted;
local checksums do not establish an external anti-rollback authority.

Startup retirement reconciliation groups at most 4096 active identities by
index prefix, validates each referenced immutable bucket once, and preserves
query order. Archived records still pass content hash, exact identity, closed
phase and receipt equality checks. `journal_replay.rs` holds replay validation;
grouped lookup neither consults a stale cache nor creates execution authority.

`update_confirmation.rs` owns process-bound readiness and the helper ACK.
Readiness keeps ActivatedUnconfirmed; receiving the ACK commits Confirmed.
Cancellation and confirmation share the update owner lock, so timeout cleanup
cannot kill a candidate after confirmation won. Critical copies validate the
actual copied bytes before atomic publication.

New activation admits at most four digest-named predecessor backups per target,
each at most 512 MiB and together at most 2 GiB. The bounded directory scan
rejects redirected or malformed matching evidence; retained predecessor files
are not automatically deleted. Recovery of an already admitted update bypasses
new-backup admission. Staged cleanup removes only the exact digest-bound file
owned by the completed or cancelled lifecycle.

Failure rollback first verifies that the installed target is still the admitted
candidate or predecessor. An unrelated target is preserved and recorded as
RecoveryRequired. The installed target has one coordinated installer owner;
out-of-band writes during a check-to-rename interval are outside this ownership
contract, because the filesystem replacement is not a compare-and-swap.

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
write amplification and bounded history paging. The audit revision adds
20 fresh-process observations per open/rebuild population, a blocking 25 ms
64-receipt page p95, a 2 MiB retained serialized-page ceiling and a 256 MiB
active-subject RSS ceiling. Serialized bytes are not allocator accounting.
OS page cache is uncontrolled; these observations do not measure cold-disk I/O.

The exact-source storage job runs both ignored qualification subjects on Linux
with the same optimized release profile used for product binaries. Raw samples
bind the compiled profile; debug measurements are diagnostics and are rejected
as qualification evidence.
The active subject measures 12,288 state transitions, fresh-process reopen,
64-receipt page latency/retained bytes, snapshot, WAL and peak RSS.
Nearest-rank p95 is derived from complete 20-process sample arrays; validators
recompute percentiles and reject short, substituted or non-finite populations. `strace -ff -yy` records successful write/pwrite and
fsync/fdatasync calls whose descriptors resolve inside the qualification root.
The retirement subject builds one million exact identities, verifies indexed
cold open and requires deterministic legacy-index rebuild. It also measures
20 actual journal opens with both 4096 active records and one million retired
identities, followed by history pages spread across all 64 active-history pages.
The same open, history and RSS ceilings apply to this combined population.

Legacy rebuild validates every immutable segment and committed archive before
promoting the indexed head. `retirement_rebuild.rs` writes identities to private
rooted, no-follow CreateNew spools, validates the held handle against its write
checksum and constructs each final prefix bucket once. Spool entry and byte ceilings apply before each append. Serialized final buckets
are checked against their byte ceiling before publication. Only current-attempt owned spools are cleaned.
The deterministic complete-authority-chain namespace prevents crash retries from
creating additional spool sets. A collision preserves the existing file and
fails closed; an operator must preserve and explicitly move crash remnants before
retrying. Pre-publication failures leave the old head; failure after atomic head
publication and during synchronization means the commit outcome is uncertain.

`retirement_qualification_fixture.rs` is test support, not an executable test.
It constructs 977 canonical mixed-prefix segments in chronological 1024-identity
batches. The million subject is legacy identity-only tombstones, not a capacity
measurement of one million full archived receipts. Each of 20 first-migration
workers starts in a distinct private root with zero derived assets, hardlinks
only immutable authority segments and copies the v2 head. Every worker verifies
actual segment shape and its rebuilt head digest; old prefix-clustered or
reused-asset measurements are rejected as qualification evidence.


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

The audit revision has passed 212 local application regressions, 210 related
owner regressions and strict application/owner Clippy. These Linux container
checks do not establish the complete same-source CI or target-platform result.
Equivalent verified-resource Open/Reveal adapters on macOS and Windows remain
a product implementation gap. Promotion also requires:

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

## 14. Adversarial audit revision

Read `ADVERSARIAL-AUDIT-20261001.md` for reproduced defects, fixes and local
verification. The previous implementation source remains provenance; a new
ordinary source commit must be frozen before qualification. Exact filenames,
input caps, stable focus IDs and a 4 MiB worker-rendered diagnostic cache keep
presentation bounded without changing final-use authority. Explicit staged
package cleanup preserves unrelated files and predecessor recovery evidence.
