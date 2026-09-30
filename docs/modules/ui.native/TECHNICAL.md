# ui.native technical development guide

**Module:** `ui.native`  
**Owner / deputy:** `ui-platform` / `accessibility`  
**Canonical branch:** `work/ui-native-qualified-integration-20260928`  
**Convergence branch:** `work/ui-native-exact-convergence-20260930`  
**Immutable implementation source:** `a417e5756d4dba18737b9d3e6aa8b13016c23662`  
**Implementation tree:** `76c085b09b249be772deae1ce8fdbab0acfb0908`

This is an implementation candidate, not a production-qualified or
release-authorized product. The ordinary source history is
`9213ff850d3dd91f8734ec954e1e5981db3480fa` →
`4bc29cf124dc5532d04349e478bc82f5d4959fd9` →
`0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17` →
`392c11672192d94afe8f878c2c94199e5be41ac4` →
`a417e5756d4dba18737b9d3e6aa8b13016c23662`. The WAL/index implementation is
ordinary Rust source. The later source commits remove the self-mutating
qualification graph, harden platform launcher identity, normalize with the
pinned formatter and add exact-source scale/durability qualification subjects.

Read `CURRENT_SOURCE.json`, `CURRENT_DELIVERY.json`,
`IMPLEMENTATION_MAP.json`, `QUALIFICATION_MANIFEST.json` and
`REVIEW_DIFF.md` together. Missing, cancelled, skipped, stale-SHA or
mismatched-parent evidence is failure. A source file or unexecuted test is not a
passing receipt.

## 1. Identity, mission and ownership

The module supplies native desktop presentation, authenticated runtime reads,
bounded local platform operations, durable observations and signed-update
coordination. It does not create a second domain store, provider executor,
authority issuer, release selector or deployment owner.

The native process owns local presentation, one runtime instance, its operation
journal and update coordination state. The gateway owns authenticated read
transport. The kernel final-use owner retains grants, nonce consumption, epoch,
expiry and revocation. Platform policy is an additional ceiling, never a
replacement for authority. Accessibility and release acceptance remain
independently reviewed facts.

## 2. Source binding and implementation status

`apps/hepta-native` is the standalone Rust application. The retired JavaScript
prototype is not a product entry point. The implementation is bound to the
commit and tree above. Later metadata commits are permitted only when the
qualification checker proves that product implementation paths are byte-for-byte
unchanged from the frozen source.

The only module qualification workflow is
`.github/workflows/ui-native-qualification.yml`. It has read-only permissions,
checks out explicit SHAs, retains an immutable worktree and never applies,
commits or pushes source. Sixteen overlapping apply-once, materializer,
source-export and derived qualification workflows were removed. Patch capsules
are not source delivery.

Current state is `implementation-candidate / qualification-blocked /
release-not-authorized`. Journal v7, WAL v1, exact active lookup, retirement
indexing and full-scale storage qualification code are implemented. Executed
crash, scale, physical-platform and signed-release evidence is not yet
established.

## 3. Boundary, responsibilities and non-goals

Permitted local state includes window/focus coordination, exact dispatch facts,
opaque session references, operation receipts and update recovery records.
Runtime truth, model or memory mutation, private signing keys, credential
issuance and release decisions remain with existing owners.

Missing authority, stale presentation, changed payload semantics, unsafe
persistence, contradictory identity or unknown effect result fails closed. A UI
timeout does not prove an admitted operation was cancelled. Closing observation
ends local observation only; it does not transform UNKNOWN into success or known
non-execution.

## 4. Internal architecture and component decomposition

`main.rs` composes endpoint trust, keyring, policy, journal, final-use gate,
updater and GUI. `backend.rs` and `native_http.rs` implement authenticated
loopback reads. `security.rs` binds an exact displayed view and payload to the
final-use owner.

`journal.rs` owns the active state machine and exact
`HashMap<OperationKey, usize>` lookup. `journal_storage.rs` owns snapshots and
framed WAL persistence. `retirement.rs` owns immutable segments, archived
receipts and a rebuildable disk index. `private_state.rs` rejects unsafe roots,
redirects and permissions.

`ui.rs` owns presentation and the supervised mutation task.
`ui/task_supervisor.rs` linearizes cancellation and owner admission.
`ui/native_picker.rs` owns a platform dialog process and exact single-use ticket.
The current UI still copies active history into presentation state; persistent
history paging and a formal immutable read-snapshot lane remain open work.

`storage_qualification_tests.rs` is test-only and cannot authorize product work.
It drives 4096 active identities through the real journal and one million
retired identities through the real retirement store, emits exact-source JSON,
and exercises deterministic legacy-index rebuild. The workflow separately
measures Linux write and sync syscalls so final file size is never substituted
for write amplification.

## 5. Contracts, ports and compatibility

The upstream port remains `ModulePort::runtime.agentd::ui.native`. Runtime reads
require a verified endpoint manifest, explicit loopback address and protocol 2.
Keyring-MAC proofs bind route, time, nonce, process incarnation, response status
and body. Read authentication never grants an OS effect.

Legacy bearer consumers are a separate compatibility surface and cannot become
an implicit native downgrade. A health response is not GUI readiness. A GUI
callback is not physical display, keyboard, IME or screen-reader acceptance.

## 6. Journal, WAL and checkpoint protocol

The active writer uses `hepta.native-operation-journal.v7`. Every state-changing
upsert appends one framed `hepta.native-operation-wal.v1` entry with monotonic
sequence, previous-entry checksum, complete validated record and entry checksum.
The frame has fixed magic, bounded length and payload SHA-256. The file is
synchronized before memory changes.

Checkpointing is bounded by WAL entry count and bytes:

1. validate current records and retirement checkpoint;
2. serialize a checksummed v7 snapshot with the WAL frontier;
3. preserve the prior snapshot as forensic evidence, never automatic replay;
4. atomically replace and synchronize the snapshot and parent directory;
5. only then truncate and synchronize the WAL.

Open validates the private root, snapshot, retirement checkpoint and full WAL
chain under one lock. A final incomplete frame may be truncated to the last
verified boundary. Bad magic, invalid length, checksum mismatch, sequence gap,
previous-checksum mismatch, illegal transition or record conflict fails closed.
A persistence error fences the owner; reopen and reconcile rather than retrying
through the same object.

## 7. Retirement authority and acceleration

Immutable retirement segments and content-addressed archived receipts are the
audit authority. `hepta.native-retirement.v3` publishes a checkpoint-bound
`hepta.native-retirement-index.v1` manifest whose bounded buckets map exact
identity digests to optional receipt digests. Manifest, buckets and cache are
acceleration only.

A missing, stale or corrupt index may reject work or trigger deterministic
rebuild, but it must never make a retired identity executable. Legacy chains are
validated and rebuilt under the same owner. Segment and record publication
precedes the indexed head. A regressed or unrelated checkpoint is rejected.

The local chain detects partial rollback and corruption. It is not an external
anti-rollback authority if every local file is restored consistently.

## 8. Runtime, concurrency and transaction model

There is one runtime and journal owner. Waiting for the mutex is not admission.
`TaskAdmission::begin()` linearizes cancellation against owner entry. After
admission, the worker remains owned and must finish the durable protocol;
shutdown never detaches it or starts a replacement effect.

The effect order is immutable validation → adapter confirmation resource →
durable Prepared → local permission → final-use claim/current revalidation →
durable Invoking → final policy and verified-use fence → OS adapter → durable
terminal or Indeterminate observation.

An exact duplicate is a read, not another effect. Reuse with changed endpoint,
session, subject, revision, action, payload, binding or grant is a conflict.
Once the OS boundary may have been crossed, errors remain uncertain unless an
operation-bound trustworthy observation resolves them.

## 9. GUI readiness, shutdown and recovery

Readiness persistence runs in the supervised owner rather than a paint callback.
A first callback records exact view identity; a later callback for the same view
creates a witness. The worker revalidates session, runtime generation, displayed
revision, content digest and module identity before recording startup or
confirming an update.

Shutdown blocks new work, invalidates actionable presentation and attempts
pre-admission cancellation. Admitted work is joined. Update activation is denied
when clean closure is not established. This is not a promise that arbitrary OS
work can be forcibly cancelled within a UI deadline.

Cold-restart qualification must exercise Prepared, Invoking, partial WAL,
checkpoint replacement, WAL truncation, retirement publication, update handoff
and rollback cut points. Source recovery logic is not a process-kill receipt.

## 10. Security and privacy controls

The shell cannot mint grants. Signing keys, complete grants, shared keyring
material and bearer-equivalent secrets must not enter UI state or logs.
Diagnostics expose stable identity, phase, low-cardinality error and digests
rather than raw payloads.

`OpenPath` and `RevealPath` remain disabled. Canonicalization, an allowlisted
root or a chooser string does not close the final name-substitution window. They
may be enabled only by an adapter consuming an already verified OS resource
capability without reopening a mutable name.

Clipboard success requires exact immediate readback. Notification launcher exit
never proves delivery. Windows notification remains disabled until packaged
identity, AppUserModelID and WinRT integration exist. macOS and Linux helpers use
fixed `/usr/bin` executables, clear the inherited environment and reintroduce
only required locale/user/session variables.

## 11. Native file input and cancellation

Each grant, update manifest or package selection is armed with an exact target
and monotonic ticket. A stale callback, screen change, cancellation or target
replacement cannot populate another field. Drag/drop uses the same target
binding. The selected path remains untrusted input and is reopened through the
bounded regular-file reader.

Current adapters are static macOS `osascript`, Windows OpenFileDialog and Linux
`/usr/bin/zenity`. Output is bounded to 16 KiB, strict UTF-8 and one absolute
path. Control delimiters, multiple paths and relative paths are rejected. Linux
`xdg-desktop-portal` is still required as the primary sandbox/Wayland route;
`zenity` may remain only as an explicit qualified compatibility route.

## 12. Performance, capacity and hot-path policy

Blocking provisional budgets live in `apps/hepta-native/STORAGE_BUDGETS.json`:
4096 active records, one million retired identities, bounded WAL/snapshot bytes,
mutation p50/p95/p99, cold-start p95, peak RSS, deterministic index rebuild and
write amplification.

The active index removes linear exact lookup. WAL avoids a full snapshot on each
ordinary transition and checkpoints at bounded pressure. The retirement bucket
index bounds ordinary exact lookup without becoming authority. UI pagination
bounds drawing only; runtime-to-UI history copying remains proportional to
active history and requires a generation-bound persistent page API.

The exact-source storage job runs both ignored qualification subjects on Linux.
The active subject measures all 12,288 state transitions, cold reopen, snapshot,
WAL and peak RSS. `strace -ff -yy` records successful write/pwrite and
fsync/fdatasync calls whose descriptors resolve inside the qualification root.
The retirement subject builds one million exact identities, verifies indexed
cold open, projects the same authoritative checkpoint through the legacy-v2
migration path and requires the rebuilt v3 head to be byte-identical.

`scripts/qualify_hepta_ui_native_storage.py` rejects wrong source identity,
missing traces, missing sync calls, count mismatch, nondeterministic rebuild and
any hard-budget breach. It produces an immutable combined artifact but does not
set production, deployment or release flags.

## 13. Observability and operations

Operators see prepared-not-dispatched, awaiting observation,
terminal-observed and observation-closed-UNKNOWN as distinct states. UNKNOWN is
never rendered as cancellation or success. Journal pressure is reported before
the active ceiling. Compaction executes through the owner and archives complete
records before active removal.

Exact-head and ordered-parent-merge evidence remains separate. Primary job
results, run IDs, runner image, logs and artifact digests are retained. A summary
cannot override failed, cancelled, skipped or missing primary evidence.

## 14. Verification and qualification

Use Rust 1.95.0 and locked dependencies. The read-only workflow runs source
identity, rustfmt, all-target/all-feature check, strict Clippy, all native Rust
targets, Python convergence/package-security contracts and Linux/macOS/Windows
exact-head subjects. Pull requests also run fixed ordered-parent merge subjects
on all three platforms. Linux additionally runs the exact-source 4096-active and
one-million-retired storage qualification and retains raw syscall/JSON evidence.
The aggregate fails when any applicable primary subject fails, skips or is
cancelled.

Repository qualification additionally needs compiler-negative API tests,
process-kill, cold restart, corruption, updater rollback, installed-package E2E,
measured coverage and sustained physical-host profiles. Physical acceptance
covers Windows, macOS, X11, Wayland, multiple displays, high DPI, Chinese IME,
screen readers, keyboard navigation, shutdown, update and crash recovery.

`QUALIFICATION_MANIFEST.json` remains pending until every required subject is
bound to the same immutable implementation source and accepted independently.

## 15. Signed updates, packaging and release

Signed manifests bind channel, target, package, predecessor, evidence, protocol,
selector/generator identities and validity. The helper re-verifies package and
predecessor. `ActivatedUnconfirmed` cannot be cleared by static self-test or exit
zero. Readiness requires the installed process, handoff, authenticated view and
GUI witness. Unsafe recovery remains `RecoveryRequired`; rollback cannot replace
an unrelated newer binary.

Release qualification separately requires installed packages, Developer ID and
notarization, Authenticode and packaged identity, Linux package ownership, key
custody/rotation/revocation, SBOM and provenance. Source tests and unsigned
archives do not satisfy these gates.

## 16. Development workflow and remaining work

All source changes are ordinary reviewable commits. Qualification is read-only.
A formatter or repair proposal must be committed and the new exact source
requalified. Required GitHub administration is recorded in
`BRANCH_PROTECTION.md`; a checked-in contract does not enable a ruleset.

Remaining work is explicit: persistent history paging, split picker/read/mutation
lanes without another state owner, verified resource handoff, portal-first Linux
picker, packaged Windows notification, executed crash and installed-package
qualification, physical accessibility acceptance and signed release evidence.
Until those gates close, `productionQualified`, `deploymentQualified` and
`releaseAuthorized` stay false.
