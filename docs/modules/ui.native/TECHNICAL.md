# ui.native technical development guide

**Module:** `ui.native`
**Owner / deputy:** `ui-platform` / `accessibility`
**Canonical branch:** `work/ui-native-qualified-integration-20260928`
**Convergence branch:** `work/ui-native-adversarial-audit-20261001`
**Immutable implementation source:** `d5445993e9ac96626bf9314053df77eeedb90e4d`
**Implementation tree:** `4f56b2375ff2a24a07a9edff0fee4135b785581d`

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
7. historical adversarial audit source `ed5fd2229502099addd6bedec2fae18783d5c162`;
8. historical audited source `32310eefbef2a80164b669fe3bfcaef69b47b9da`;
9. cross-platform source/ACK fixture repair `85185bcb274682ece9da5086813fd60cc2a7214a`;
10. historical test-profile hashing repair `0c176c9d4df6055418529389bf0f749f74ac1a69`;
11. historical checkout/strict-platform/registrar ABI repair `ebd04a7ed458aa5feaba69525f48f3623c4db033`;
12. historical Unix executable/Windows authority fixture repair `703e9bf2871b26d646f1c4d748e0b0061f70ad3c`;
13. historical Darwin private-permissions, Unix authority FIFO and Windows typed registrar-probe repair `a1abe5b2a083213c095cdabaf4b3048144e3cad0`;
14. historical Darwin private-state fixture admission repair `b5378e29d0fe191225abe853d848b498552f5850`;
15. historical private retirement-fixture baseline repair `89c64152c9b971fcaabe98aeb0d24452e1c6e30d`;
16. Windows private atomic-publication repair `403df62a7bf3ac065f2b0ad21661d08b66b32731`;
17. cancelled late-ACK fixture repair `ee6a155661ad7e051a25d90eb5cc37ca1ce5d5b4`;
18. current deterministic merge LF identity repair `d5445993e9ac96626bf9314053df77eeedb90e4d`.

Patch capsules, apply-once workflows and CI-created product commits are not
source delivery. The sole module workflow has `contents: read`, checks explicit
SHAs and never applies, commits or pushes source.

## 3. Internal architecture

`main.rs` composes endpoint trust, keyring, policy, journal, final-use gate,
updater and GUI. `backend.rs` and `native_http.rs` implement authenticated
loopback reads. `security.rs` binds an exact displayed view, payload and optional
resource identity to the final-use owner.

`codex-rs/utils/private-state` owns reusable Windows ACL, handle identity,
durable replacement and Darwin private-permission primitives. Shared contracts depend directly on this
utility; `hepta-private-state` remains a compatibility export for the native
application. Domain authority stays with the calling owner. This avoids a
shared-contract dependency on a product module while preserving OS behavior.

Windows file validation checks regular-file identity, owner and DACL on the
same opened handle, including child ACL drift beneath a still-private root.
The shared utility's read/write `open_file` also requires one hardlink; shared
contract callers cannot bypass mutable-file checks by using that entry point.
Native write, append, lock and create opens reject multiple hardlinks on Unix
and Windows. Windows private snapshots and update staging also check the exact
atomic temporary before first bytes and before publication, reject an existing
destination with an unsafe DACL, and recheck private copy sources. Shared utility
replace validates the staging file and existing target first, releases its
non-delete-sharing verifier handles, rechecks the held root, then renames and
verifies the published child. A trusted owner can change children between the
validation/close and rename steps; this protocol is not a filesystem CAS fence.
Fifteen new Windows tests retain original bytes/ACLs and cover safe publication,
same-handle temporary drift, existing target drift, source drift and hardlinks. Native Unix Read opens do not chmod private owner-only files
(including modes 0400, 0500, 0600 and 0700), and linked immutable migration inputs
remain readable subject to content and identity validation. A trusted principal
can still add a link after validation; these checks do not create domain
authority or an OS-wide ownership guarantee.

Private state requires a trusted filesystem and mount configuration that enforce
advertised owner and permission semantics. An absolute path does not establish
filesystem locality. Linux verifies UID, mode, type, links and identity; remote
named ACLs and mount policies need their own deployment qualification. For
example, [NFSv4 section 6.3.2](https://www.rfc-editor.org/rfc/rfc7530.html#section-6.3.2)
derives mode from selected principals, while the Linux
[CIFS documentation](https://www.kernel.org/doc/html/latest/admin-guide/cifs/usage.html)
describes mount options that disable client permission checking. Current local
POSIX execution does not establish privacy for those configurations.

On macOS, `codex_utils_private_state::verify_private_permissions` checks the
same opened descriptor through the Darwin ACL API and typed `fstatfs`. Private
roots, children, journal files, update locks/staging and final-use/lease state
reject every extended ACL entry, including deny-only entries, query failures,
unsupported queries and mounts with `MNT_IGNORE_OWNERSHIP`. UID, mode, identity,
regular-file and applicable hardlink checks remain separate requirements.

The wrapper accepts an absent ACL only for Darwin's documented `ENOENT` path;
a returned ACL is validated before iteration. Darwin entry success is zero,
and only `-1/EINVAL` on a valid empty ACL admits an empty list. ACL allocations
are freed without changing filesystem permissions. Callers retain
`forbid(unsafe_code)`; the small OS utility owns the FFI boundary.

Checks precede permission migration, private bytes/truncation and atomic
publication. Held roots, the staging descriptor and any existing destination
are checked again before replacement; a destination carrying an ACE is
preserved instead of silently replaced with a private temporary. Native
boundary tests inject actual ACEs after open and file sync. External installer
targets/downloads/backups do not acquire this private-state policy. All Unix
shared authority-store opens additionally use `NONBLOCK` before type validation
so an owner-only FIFO is rejected without waiting for a writer.

Create private fixture baselines with the existing
`tests/common/snapshot.rs::write_private_json` helper or create_new/mode0600;
create private directories with mode0700. Assert those baseline modes before
injecting a fault and assert the requested cut actually executes. Recovery
fixtures need valid private predecessors; intentionally unsafe predecessors
should test rejection. Public downloads, installed binaries and configuration
inputs retain their own input policy. Fixture-only ACL removal is confined to
fresh owned controls.

Real macOS ACL fixtures require unchanged 0700/0600 modes and compare original
bytes and ACLs. Fixture-only ACL removal establishes a control solely on newly
created owned temporary directories; production never removes an ACL. Source
presence and Linux execution do not qualify Darwin behavior. An ownership-ignored
volume still requires a real target-host mount receipt; no static bit assertion
or current ACL fixture is presented as that receipt. A trusted owner may change
permissions after validation; these checks do not provide filesystem transactions
or independent authorization.

The Windows utility defines that identity as the process primary token's
`TokenUser`, read by `current_user_sid()` through `OpenProcessToken`.
Creation relies on the OS default owner. Microsoft's
[Owner of a New Object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)
contract derives new-object ownership from the creating primary or impersonation
token's `TokenOwner`; [TOKEN_OWNER](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_owner)
can name a legal user or group SID. A different default owner can therefore
create an object that strict subsequent owner verification rejects. The current
support and qualification precondition is default-owner SID equal to primary
`TokenUser`, with no thread impersonation. This is a conditional fail-closed
availability limitation, not an observed exploit or a claim that elevation
always fails. Physical Windows ordinary, elevated, owner-mismatch and
impersonation cases remain unqualified; satisfying the precondition alone does
not establish platform acceptance.

`journal.rs` owns the active operation state machine and exact
`HashMap<OperationKey, usize>` lookup. `journal_storage.rs` owns snapshots and
framed WAL persistence. `retirement.rs` owns immutable segments, archived
receipts and a rebuildable disk index. `private_state.rs` retains directory identity and rejects unsafe roots,
redirects and permissions. Unix journal reads and mutations use the pinned
directory descriptor; atomic replacement verifies its parent descriptor and
synchronizes that same directory. Operator-selected ancestry remains trusted;
local checksums do not establish an external anti-rollback authority.

`StartupRecorder` pins an already provisioned private parent at construction;
it does not create an absent parent. Publication validates the exact session
and view identity and uses the rooted atomic JSON writer. Parent replacement
rejects publication instead of redirecting the observation. The startup record
describes a completed GUI frame callback and keeps acceptance/release flags
false.

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

The acknowledgement regression gives readiness and post-helper exit their own
20-second observation deadlines; timeout diagnostics retain child status,
elapsed time and pending-state observations. Full debug-symbol executables are
still verified in their entirety. Test-only SHA-256 optimization in
`[profile.test.package.sha2]` keeps that real subject within its fixture budget;
it does not change production 5/35-second deadlines, digest semantics or the
update-owner arbitration fence. The 31.353-second full-symbol readiness failure
before this optimization remains a failed diagnostic, not a qualified receipt.

Pending/result JSON reads, atomic writes and removal, owner/runner locks and
readiness/ACK/cancellation transitions retain the update `PrivateStateRoot`.
Contention retries the same pinned owner; directory replacement remains an
error. The updater helper activates through its existing `UpdateManager`,
preserving that manager's root identity across runner locking and activation.
The standalone activation entry point establishes one root identity at entry.

The staged directory is a verified private child capability. Copy, digest
checks and cleanup retain that child identity; Unix atomic staging publication
compares the held parent descriptor with the pinned child before commit.
Legacy staging permissions are tightened through verified current-principal
handles; file permission migration requires one hardlink. New stage admission
allows an empty directory or one exact current-digest `.package` whose bytes
match a retry. Another digest, unknown entry or crash temporary is preserved
and rejects admission until explicit operator recovery. Each package is bounded
to 512 MiB. Atomic replacement can transiently retain an additional 512 MiB
copy, so this is not a 512 MiB peak-directory guarantee.

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

`ui/binding_prepare.rs` prepares resource-bound input in the supervised runtime
lane because confirmation can perform OS I/O. It captures the exact subject,
operation, action, payload and authenticated `RuntimeView`, then rechecks that
view under the runtime owner before calling confirmation. A result is displayed
only if the Operations screen, connection, full view identity and captured
input still match. Edits or stale completion discard it. Cancellation before
admission does not call the confirmation owner; shutdown drains admitted work.
Preparation does not invoke an effect, mint a grant, select nonce/epoch/lifetime
or sign authority. The independent authority owner signs the complete grant.

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

A safe non-Linux implementation requires an authenticated cooperating receiver
that directly consumes the retained resource capability. Windows can use
[DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)
into a held, verified target process; macOS can use XPC descriptor transport.
Versioned canonical resource identity must include the OS object and receiver
identity/contract in the existing request.v2 resource_digest. Independent
issuer owned by kernel.authority signs the proposal; hepta-contracts defines
canonical binding and verification. ui.native owns transport, capability lifetime
and receiver consumption.

Retain the parent capability until an operation/session/grant/resource-bound
admission ACK confirms the receiver holds its duplicate. Lost ACK, timeout or
receiver death remains Indeterminate and consumes the nonce. ACK proves handoff;
a queryable operation-bound effect receipt and reconciliation are needed for
completion. Test rename/substitution, delayed reception, wrong receiver,
revocation, lost ACK and process exit. Generic default-app and Finder/Explorer
support needs an explicit cooperating receiver contract; this remains product
implementation work before physical-host qualification.

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
Marker input is a bounded regular-file read of at most 128 bytes, with strict
UTF-8 and an exact AUMID after trimming. Missing, malformed, oversized or final
symlink/reparse markers reject support. The reader does not sandbox parent
directories. The registrar copies its static readonly property key to a local
variable before passing it by `ref`. `tests/windows_registrar.rs` compiles the
actual packaged C# source in system PowerShell. The PROPVARIANT union contains
a sequential count/pointer array, matching the SDK's 24-byte x64 and 16-byte x86
layout instead of the old 16/12-byte pointer-only layout. The Windows-only test
checks `Marshal.SizeOf` and offsets on its actual host architecture and exercises
packaged property-store `SetValue` plus COM `GetValue` on an owned temporary
shortcut, with `PropVariantClear` cleanup. The
[SDK union definition](https://learn.microsoft.com/en-us/windows/win32/api/propidlbase/ns-propidlbase-propvariant)
is the ABI reference. This test has not executed on Linux and does not establish
physical Windows registration or toast delivery.

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

`ui/binding_prepare_snapshot_tests.rs` runs the actual egui widgets and painter
headlessly and snapshots visible text for pending preparation and stale-result
discard. The matching snapshot covers those presentation states; it does not
exercise a native window, GPU, compositor, IME or physical accessibility stack.

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
The retirement subject builds one million exact identities, measures fresh-process
indexed open and requires deterministic legacy-index rebuild. It also measures
20 actual journal opens with both 4096 active records and one million retired
identities, followed by 20 history pages sampled across the full 64-page range.
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
The workflow environment-context guard recognizes top-level `jobs:` block
headers with trailing whitespace or comments; a comment cannot suppress job
checks. Inline scalar values are not treated as block headers.

Repository identity checks use the canonical declared ROOT while preserving
dependency components for inspection. Legal root ancestry aliases, including
macOS `/var` and Windows short paths, do not terminate workspace discovery.
Internal symlinks and Windows `FILE_ATTRIBUTE_REPARSE_POINT` components are
rejected through `lstat`, including junctions whose destination remains inside
the repository. A local dependency cannot leave the repository and re-enter
through parent traversal or an outside alias. Windows NTFS regressions create
real `mklink /J` objects; they must execute on Windows before platform acceptance.

Metadata publication writes explicit LF and retains exact Git blob comparison;
CRLF text with equivalent JSON semantics remains byte drift. Windows shell
fixtures bind an existing Git for Windows Bash from the Git installation and
refuse unrelated Bash/WSL selection. Fixture subprocess diagnostics retain
stdout and stderr. The old Windows failure does not contain proof identifying
WSL as the selected executable; that explanation is an inference.

SBOM and provenance generation is repository-controlled evidence only. It does
not establish production signing, notarization, Authenticode, physical-host
acceptance or release authorization.

## 13. Remaining gates

The current ordinary implementation source is `d5445993e9ac96626bf9314053df77eeedb90e4d`, tree
`4f56b2375ff2a24a07a9edff0fee4135b785581d`. Windows private atomic snapshot/copy publication now validates
the existing destination and same temporary descriptor before private bytes and
before commit. Private-source copies recheck their retained source descriptor;
external installer inputs/targets keep their own policy. The shared Windows
utility validates staging and existing destinations before replacement, then
closes its non-delete-sharing verifier handles before the actual rename.
Checks reject unsafe evidence without repairing its ACL or replacing its bytes.

The cancelled-ACK fixture accepts BrokenPipe only after durable cancellation;
successful ACK delivery, candidate exit, rollback and predecessor-byte assertions
remain enforced. Qualification merge construction and reconstruction now send
fixed UTF-8 LF bytes to Git, producing the same ordered-parent commit on every
OS. The strict source/tree/parent/workflow/run/attempt checks remain unchanged.
Darwin same-descriptor ACL/ownership, Unix NONBLOCK admission, typed Windows
registrar and the three macOS baseline fixture corrections are retained.

CURRENT_SOURCE.json binds 417 Git blobs, 32 selection paths and 16 local Cargo
dependencies, inventory SHA256 `8235fbc0deffc155632c99a0258c352fd0fe61201e9eacac37e57d2351b2692d`. Production, deployment
and release flags remain false. Fifteen new Windows regression definitions
(nine native and six utility) need actual execution on this current source.

Fresh frozen-source Linux just test/nextest passed 243/243 in 2.467 s (three
independent scale entries ignored); strict all-target/all-feature Clippy passed
in 4.59 s. Python ran 239 tests in 17.416 s: 238 passed and one Windows-only
real NTFS junction case was skipped. The locked/offline three-binary release
build completed in 0.54 s and reuses unchanged Linux production artifacts; self-test and seven actual
child-fault checks passed with effect, activation and release authority false.
Complete same-run current-source platform/storage qualification remains pending.
This is the publication-time metadata capture, before the final workflow completes.
The current exact-run receipts are attached to [draft PR #1308](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1308).
The separately committed navigation guard and owner-guide precision repairs are
`9ca0e42e211e87cf3fd0d1a15ba9d484d20093a9`, tree
`9fa335e95a577c642683252b00d7f6d23708f5d7`; these scripts and guides are outside
the frozen native product closure. CI still binds the complete candidate commit.

Historical source89/candidate8c/run36832001532 actually passed all seven producer
subjects: both Linux/Windows/macOS head and merge suites plus 48 storage traces
and unchanged hard budgets. Each macOS subject executed all 32 ACL and both
Unix FIFO cases. Aggregate nevertheless failed: the Windows merge's CRLF commit
message produced b09d1a4b409537432dec6b8876e4e63843b5cd0c instead of canonical
LF merge6a3cd7ea61a6e718c1065d323ec7022b9b3d68bd, with identical tree and ordered
parents. Exact Git bytes prove the difference. This is an executable identity
defect, not a physical-host gate. Old tests also omitted the newly repaired
Windows atomic-publication calls. See [20261001-89c64-verification.json](history/20261001-89c64-verification.json); its original
18 localAudit fields and all three platform children remain historical only.

Intermediate source403's local suite passed242/failed1: the cancelled child had
already exited when the parent incorrectly unwrapped BrokenPipe. Its failed
raw log is preserved in 20261001-403df-verification.json. SourceEE6 repaired that
fixture and passed243; 20261001-ee6a1-verification.json retains those diagnostics
separately. Neither source had a completed metadata review workflow and their
results cannot qualify this new source.

Eleven affected shared-owner maps refresh complete current source observations
after the shared Cargo/contracts/utility changes. Historical sourceBase, operation
states, tests, delegates, callers, receipts and execution/acceptance/activation/
release claims remain unchanged. Navigation does not establish product execution.
The migration guard explicitly recognizes module-specific executable, host and
release qualification fields, requires actual bool values, and rejects stale
execution proof before metadata writes. Source and structural completion facts
remain distinct. Two pre-existing NDU source drifts remain whole-project blockers;
this work preserves their historical claims rather than rebinding those receipts.

Historical B537 source `b5378e29d0fe191225abe853d848b498552f5850` in candidate58/run36830035079
passed both earlier corrected fixtures, library 145/145 and all 14 native ACL
cases on macOS. Its full application suite then failed retirement recovery
because a fixture newly created head.json with default 0644 mode; each subject
had 208 passes/one failure/three ignored. Shared-owner ACL/FIFO, release and
package stages were not reached. Exact old localAudit fields and separate
actual raw failures are retained in [20261001-b5378-verification.json](history/20261001-b5378-verification.json); no
historical pass or pending field is relabeled as current qualification.

Historical A1 source `a1abe5b2a083213c095cdabaf4b3048144e3cad0` passed Linux application 243/243,
Python 237/238 with one Windows-only junction skip and isolated owner 194/194.
Its F5 run 36827460737 actually passed strict macOS lint and all 14 native ACL
fixtures, but both application suites failed two older fixture assumptions.
Shared-owner ACL/FIFO cases were not reached after application failure. The
failure and local diagnostics are retained in [20261001-a1abe-verification.json](history/20261001-a1abe-verification.json);
the distinct F5 and 8f CI candidates remain separate, and pending subjects are
not passes. This actual failure supersedes the prior review stop.

Historical source 703e9bf passed both Linux platform subjects (18 checks each),
both macOS subjects and storage (48 traces and all hard budgets) in run
36823756631. Both Windows subjects and aggregate failed the PowerShell
Marshal.SizeOf overload fixture. Its complete terminal evidence and clean-review
Linux diagnostics are retained in
[`history/20261001-703e9-verification.json`](history/20261001-703e9-verification.json).
That success does not qualify the new permission code.

Historical EBD checkout/cfg/FIFO/PATH/registrar repairs retained exact byte
checks, root validation and non-Linux Open/Reveal rejection. Its frozen inventory
was 406/32/16 with SHA256
`ec5658b2f11bc46010bb33e460fc8b287465c6a95fcd96c6248aebde8e083d36`.
Linux debug application 243/243 (5.581 s, three scale entries ignored), Python
238 total (237 passed/one Windows junction skip, 20.778 s), map 104/104
(22.123 s), package/portal 36/36 (0.167 s), projection seven tests, strict
application Clippy (150 s) and full-symbol ACK 1/1 (3.020 s) belong to EBD.
They and its actual CI follow-up are retained in
[`history/20261001-ebd04-verification.json`](history/20261001-ebd04-verification.json).
Run 36822033441 is terminal and failed overall. Identity, both Linux platform
subjects (18 checks each, including virtual GUI lifecycle) and storage succeeded;
storage retained 48 traces passing all hard budgets. macOS full tests, Windows
owner lint and aggregate failed. See the
[Linux child record](history/20261001-ebd04-linux-verification.json).
macOS full application tests failed copying absent `/bin/true`, and Windows
owner Clippy rejected five helper `unwrap` calls. These are executable fixture
failures repaired in 703e9bf, not physical-acceptance evidence gaps.

Historical verification of implementation `0c176c9d4df6055418529389bf0f749f74ac1a69`
passed 243/243 normal debug application tests in 6.377 s; three scale entries
were ignored by that normal suite. Strict debug all-target/all-feature
application Clippy passed in 9.39 s, and the full-symbol ACK fixture passed in
3.358 s. Native Python ran 236 tests successfully in 20.939 s: 235 passed and
one Windows-only junction case was skipped. Combined native-adapter and
global-map regressions passed 104/104 in 22.945 s. Package/portal passed 36/36
in 0.138 s; projection generation/verification/lint and seven tests passed.
The source checker returned structural-pass for 404 frozen Git blobs, 30
selection paths and 16 local Cargo dependencies. Structural success and local
Linux diagnostics do not constitute seven-subject or physical-platform acceptance.
These results are preserved in
[`history/20261001-0c176-verification.json`](history/20261001-0c176-verification.json).
That source's run 36820183453 passed Linux head/merge (18 checks each) and
storage with 48 actual traces and all hard budgets (artifact 11143665973), but failed macOS application Clippy with four
cfg/API issues and Windows Python when Git's `strace.exe` displaced the mock.
Partial storage success does not qualify that source or the current candidate.

Historical 32310 evidence is retained in
[`history/20261001-32310-verification.json`](history/20261001-32310-verification.json).
Its local 243 release tests, 227 Python tests, 86 map-adapter tests, release
binaries and scale measurements belong to that source. The later real CI run
36796737020 failed overall: Linux merge completed 18 checks including owner
tests, strict Clippy, compiler-negative privacy boundaries, packaging and virtual
desktop lifecycle; Linux storage passed all hard ceilings with 48 retained
traces. Linux head ACK failed, macOS Python had three failures/four errors, and
Windows Python had nine failures/six errors. Partial success supplies historical
evidence and does not promote the new candidate. Old queued observations and
the previous static-review convergence statement were superseded by these
executed failures and follow-up fixes. Earlier ed5 and ca66 evidence likewise
remains historical.

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
ordinary source commit is frozen at the identity above and requires its own
qualification receipts. The executed CI follow-up repaired cross-platform root
coordinates, source metadata byte handling, shell selection and full-symbol ACK
fixture performance while retaining fail-closed boundaries. Later real CI also
exposed macOS-only cfg/API failures and a Windows fixture PATH collision; ebd04
repaired those, checkout lock bytes and the registrar ABI. Real EBD CI then
found the macOS executable fixture and Windows helper lint failures; 703e9bf
repaired those fixtures. Subsequent 703 Windows execution and independent Darwin
ACL/FIFO review motivated the current ordinary repair and new freeze. Binding, startup,
rooted update and child ACL regressions
are in `ui/binding_prepare_tests.rs`,
`startup_tests.rs`, `update_root_storage_tests.rs`, `journal_windows_tests.rs`
and the shared utility's `windows_acl_tests.rs`. These cases validate local
ownership and substitution boundaries without minting execution authority.
Earlier bounded review stops were superseded by executed platform failures and
the independent permission review. The new source has two cross-reviews and
Linux diagnostics; target CI, ownership-ignored mounts and physical acceptance
remain required. This is not completed qualification or a claim about future
defects. New executable failures require another ordinary repair, freeze and
verification.
Exact filenames, input caps, stable focus IDs and a 4 MiB worker-rendered
diagnostic cache keep
presentation bounded without changing final-use authority. Explicit staged
package cleanup preserves unrelated files and predecessor recovery evidence.
