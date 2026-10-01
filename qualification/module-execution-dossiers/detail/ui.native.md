# ui.native: implementation and qualification dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-qualified-integration-20260928`.
Audit revision: `work/ui-native-adversarial-audit-20261001`.
Immutable implementation source: `a1abe5b2a083213c095cdabaf4b3048144e3cad0`.
Implementation tree: `6269ea8bf6f01c77a3025881e636096a4111b330`.
Status: implementation candidate; cross-platform execution, physical acceptance
and release remain separate evidence gates.

The authoritative source SHA/tree and verification state are recorded in
`apps/hepta-native/CURRENT_SOURCE.json` and
`docs/modules/ui.native/CURRENT_DELIVERY.json`. Detailed development instructions
are in `apps/hepta-native/DEVELOPMENT.md`. Read the audit findings in
`docs/modules/ui.native/ADVERSARIAL-AUDIT-20261001.md` alongside these documents.
The previous dossier is preserved in
`qualification/module-execution-dossiers/history/ui.native-before-20261001-audit.md`;
its journal-v3, 32768-retirement and single-task descriptions are historical.

## Product position and ownership

`apps/hepta-native/src/main.rs` composes authenticated runtime reads, bounded
platform operations, the operation journal and signed-update coordination.
The shell presents facts; it cannot mint grants, publish domain truth, select
releases, sign its own permissions or grant deployment authority.

The read-only loopback gateway authenticates native protocol v2 with the OS
keyring MAC contract. `kernel.authority` owns final-use grants, nonce claims,
expiry, epoch and revocation. `NativeShellRuntime` is the sole mutation and
journal owner. History and picker workers cannot become another authority.

## Durable operation contract

Identity includes endpoint, session incarnation, operation ID, subject,
displayed revision, action, payload, final-use binding and grant digest.
Exact retries read the recorded observation; changed identity semantics conflict.
The effect order is durable Prepared, current final-use claim, durable Invoking,
verified-use and local-policy fences, adapter entry, then durable observation.
UNKNOWN effects are never automatically replayed.

The current active journal is v7 with a checksummed, hash-chained v1 WAL.
Mutation synchronizes the WAL before publishing memory. Bounded checkpoints
replace and synchronize the snapshot before truncating the WAL. A previous
snapshot is forensic evidence, never an automatic replay source.

Retirement v3 binds immutable v2 segments and archived receipts to a rebuildable
disk index. Segments and archived records retain authority. Missing or corrupt
acceleration rejects or rebuilds; it cannot authorize a retired operation.
4096 active records, 8 MiB snapshots, 4 MiB WALs and bounded index buckets are
source ceilings. One-million-retirement performance is a qualification target,
not a demonstrated capacity claim. The scale fixture contains legacy identity-only
tombstones in mixed 1024-identity chronological batches. First-migration workers
start from zero derived assets; production migration uses bounded authenticated
spools and constructs each final bucket once. Crash remnants fail closed and
require explicit operator recovery. Hard budgets are in `STORAGE_BUDGETS.json`.

Windows validation checks the same file handle's owner/DACL, including child
ACL drift under a still-private root. Native mutable opens and the shared
utility's read/write `open_file` reject multiple hardlinks. Native Unix Read
does not chmod owner-only private files, and immutable migration aliases remain
readable with identity/content checks. The held-handle check cannot prevent a
trusted principal from adding a hardlink afterward.

## Platform and presentation contract

Linux file picking is XDG Desktop Portal-first; Zenity requires explicit policy.
Linux Open/Reveal binds a no-follow regular-file/directory descriptor and its
resource identity into final use, then hands that descriptor to XDG OpenURI.
Non-Linux Open/Reveal currently rejects because an equivalent resource-capability
adapter has not been implemented. This is a capability gap, not merely a missing
physical acceptance receipt.

Clipboard completion requires exact immediate readback. Notification/open helper
exit proves submission only, so uncertain effects remain Indeterminate.
The Windows unsigned package includes the AppUserModelID registrar and WinRT
toast adapter; visible installed notification requires physical-host evidence.
Notification identity input is strict UTF-8, bounded to 128 bytes and checked
against the exact AUMID. The packaged registrar's readonly property key is
copied before passing it by `ref`; a Windows test compiles the actual packaged
C# source. Its PROPVARIANT union now includes a sequential count/pointer array
for SDK-compatible x64/x86 sizes of 24/16 bytes; the former 16/12-byte layout was
undersized. The Windows-only test checks actual `Marshal.SizeOf` and offsets and
uses packaged SetValue plus COM GetValue on its own temporary shortcut, with
PropVariantClear cleanup. See the
[SDK ABI](https://learn.microsoft.com/en-us/windows/win32/api/propidlbase/ns-propidlbase-propvariant).
This test remains unexecuted on Linux and does not prove installed identity or
visible toast acceptance.

The GUI supervises mutation, bounded history-read and native-picker lanes.
Read and mutation admission are mutually exclusive. History pages are bounded
to 256 records; the GUI requests 64. Escape cancels pre-admission tasks on every
screen. File-input tickets preserve exact target and filename identity.
Shutdown joins all lanes and closes the runtime before update activation.

Resource-bound grant preparation runs in the supervised runtime lane, captures
the exact subject/operation/payload/authenticated view, and rechecks that view
under the runtime owner before confirmation. Completion is displayed only for
the unchanged input, screen, connection and full view identity. Cancellation
before admission never calls confirmation; admitted work is drained at shutdown.
The prepared binding remains input for the independent authority owner, with
no effect entry, grant creation or signing. The actual egui pending/stale text
snapshot is headless evidence, not GPU or physical-platform acceptance.

## Update contract

Independent signatures bind channel, target tuple, candidate, predecessor,
evidence, compatibility and lifetime. Critical copies hash the actual source
handle and verify copied bytes before atomic publication. Recovery cannot
overwrite an unrelated target.

Startup recording pins an existing private parent and rejects parent
substitution. Updater JSON reads/writes/removal, owner/runner locks and handoff
transitions use retained private-root capabilities. The helper activates through
its existing manager's pinned root. Staging retains a verified child capability
and admits only an empty directory or one exact current-digest package retry.
Unknown, abandoned or crash-remnant entries are preserved for explicit operator
recovery. The 512 MiB package bound permits an additional transient atomic copy;
it is not a 512 MiB peak-directory guarantee.

New-process readiness is process/session/view-bound. Readiness alone leaves
ActivatedUnconfirmed; the candidate commits Confirmed only after receiving the
helper acknowledgement. Failed or unobserved startup remains recoverable.
Rollback failure preserves RecoveryRequired.

The full-symbol ACK fixture uses separate 20-second readiness and post-helper
exit observations with child/pending-state diagnostics. Test-profile `sha2`
optimization hashes the complete actual executable, including debug symbols;
production 5/35-second deadlines, digest checks and owner fencing are unchanged.
The earlier 31.353-second readiness failure is retained as failed history.

## Required evidence

The read-only `ui-native-qualification.yml` evaluates exact head and a fixed
ordered-parent merge on Linux, macOS and Windows, plus exact-implementation Linux
storage qualification. Output directories are separate from the checked-out
source. The aggregate requires one run/attempt and revalidates source, workflow,
lockfiles, logs, package, SBOM, provenance and storage evidence.

Qualification path checks canonicalize the declared root alias but inspect raw
dependency components with `lstat`; internal symlinks and Windows reparse points
remain forbidden, even when a junction target is within the same repository.
Outside aliases and parent traversal cannot escape and re-enter. Metadata uses
explicit LF plus exact committed-byte comparison. Windows shell fixtures bind
Git for Windows Bash explicitly; the old failed process output did not prove
which shell implementation had been selected. The actual NTFS junction fixture
must run on Windows; skipping it on Linux gives no Windows pass.

Required cases include duplicate/revoked effects, real process death after
Invoking, WAL corruption/partial tail/checkpoint recovery, root and file
substitution, retirement rebuild, update-copy drift, helper acknowledgement loss,
rollback failure, stale picker tickets and shutdown of every lane.

The current ordinary implementation source is `0a129b41c2a2d42ca907ea8257bf780108bc664f`, tree
`f90313f067446c629b8da50058ee1bd2101e76e7`.

Native update owner, handoff and runner locks now return an opaque
`updater::UpdateLock` instead of exposing a File. Successful acquisition builds
one lifetime guard; dropping it explicitly unlocks before closing the handle,
including a failed post-acquisition root check. Failed acquisition never
unlocks another owner. Retain the runner guard for the existing orchestration
scope. Final-use and authority-lease stores also unlock on their last owner
Drop, including failed trust construction; Arc/token ownership remains intact.
No retry, test serialization, deadline change or new authority was introduced.

Windows private atomic snapshot/copy publication now validates
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

CURRENT_SOURCE.json binds 420 Git blobs, 32 selection paths and 16 local Cargo
dependencies, inventory SHA256 `8865ed312eaff178ad8909e2e1fadb3a53ec009fe8297f5e09692afb4c3b58e6`. Production, deployment
and release flags remain false. Fifteen Windows atomic/ACL regressions remain in the new-source target suite;
passing D544 executions are historical evidence only.

Precommit Linux diagnostics for the lock repair passed application 245/245
(2.460 s; three independent scale entries ignored) and strict all-target/all-feature
Clippy (8.67 s). The exact-copy reduced contracts workspace passed focused 2/2
and full all-feature 196/196 (1.028 s), scoped fix and strict Clippy. These are
local diagnostics, not immutable-candidate qualification; the standard owner
workspace's offline metadata attempt stopped on an unrelated uncached imbl
package. The public UpdateManager runner API also passed a controlled fork
red/green with the same harness. Current qualification-tooling Python passed 239/240 in 15.191 s (one Windows
NTFS-only skip). Three locked/offline release binaries built in 23.09 s; binary
self-test and seven actual child-fault checks passed locally, with all effect,
activation and release authority false. A new complete same-run current-source
platform/storage run and packaged-artifact evidence remain required.
This is the publication-time metadata capture, before the final workflow completes.
The current exact-run receipts are attached to [draft PR #1308](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1308).
The separately committed navigation guard and owner-guide precision repairs are
`9ca0e42e211e87cf3fd0d1a15ba9d484d20093a9`, tree
`9fa335e95a577c642683252b00d7f6d23708f5d7`; these scripts and guides are outside
the frozen native product closure. CI still binds the complete candidate commit.

Historical D544 candidate632d/run36838749224 completed FAILURE. All three
actual merge subjects matched canonical LF SHA7d22e1fa3576681ae721fe3effb4a30f6806ec2a.
Linux head (243 application/212 owner), macOS head (254/230), both Windows
subjects (209/173, including all fifteen named atomic/ACL regressions) and all
48 storage traces/hard budgets passed. Linux merge failed on update-lock
contention; macOS merge failed the legacy fixture's precise InvalidTrust
assertion, without printing its actual variant. Aggregate correctly stopped at
the failed-subject gate; deep aggregation and acceptance did not run.

Controlled same-Rust flock/fork, public UpdateManager API and actual Store
alias experiments reproduce the close-only lock lifetime defect. Explicit
unlock passes while inherited descriptors remain open and preserves the
successor's lock. These experiments prove a fixable mechanism and API defect;
the precise original CI scheduling cause remains unproved
(actualCiCauseProven=false). The original eighteen metadata fields, exact
platform children and later terminal observation are retained in
[632d historical record](../../../docs/modules/ui.native/history/20261001-d544-632d-verification.json); no pass is inherited by this new source.

Historical candidate dc59/run36836809639 completed FAILURE: immutable identity
and storage succeeded, both macOS subjects failed shell parsing before checks,
and Linux/Windows correctly rejected productExecutionComplete=0 but failed the
fixture's stale error-message expectation. Both Linux and Windows merge subjects
actually matched
658914a3e602337e707901a9f8d11388b6486799; no Mac merge or Rust/ACL pass was observed.
The producer now defines its Python heredoc in a standalone shell function,
outside quoted command substitution, preserving fixed binary LF and every
identity check. The regression executes head and merge with Python single/double
quotes and an apostrophe comment, using native /bin/bash on macOS. The malformed
bool fixture now requires its precise rejection diagnostic; input0 and denial
remain. Forty-eight targeted regressions passed locally. Actual new-platform
execution is required. See [dc59 historical failure](../../../docs/modules/ui.native/history/20261001-dc59-verification.json); its original 18
localAudit fields and independently captured platform children remain unchanged.

Historical source89/candidate8c/run36832001532 actually passed all seven producer
subjects: both Linux/Windows/macOS head and merge suites plus 48 storage traces
and unchanged hard budgets. Each macOS subject executed all 32 ACL and both
Unix FIFO cases. Aggregate nevertheless failed: the Windows merge's CRLF commit
message produced b09d1a4b409537432dec6b8876e4e63843b5cd0c instead of canonical
LF merge6a3cd7ea61a6e718c1065d323ec7022b9b3d68bd, with identical tree and ordered
parents. Exact Git bytes prove the difference. This is an executable identity
defect, not a physical-host gate. Old tests also omitted the newly repaired
Windows atomic-publication calls. See [20261001-89c64-verification.json](../../../docs/modules/ui.native/history/20261001-89c64-verification.json); its original
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
actual raw failures are retained in [20261001-b5378-verification.json](../../../docs/modules/ui.native/history/20261001-b5378-verification.json); no
historical pass or pending field is relabeled as current qualification.

Historical A1 source `a1abe5b2a083213c095cdabaf4b3048144e3cad0` passed Linux application 243/243,
Python 237/238 with one Windows-only junction skip and isolated owner 194/194.
Its F5 run 36827460737 actually passed strict macOS lint and all 14 native ACL
fixtures, but both application suites failed two older fixture assumptions.
Shared-owner ACL/FIFO cases were not reached after application failure. The
failure and local diagnostics are retained in [20261001-a1abe-verification.json](../../../docs/modules/ui.native/history/20261001-a1abe-verification.json);
the distinct F5 and 8f CI candidates remain separate, and pending subjects are
not passes. This actual failure supersedes the prior review stop.

Historical source `703e9bf2871b26d646f1c4d748e0b0061f70ad3c` has fresh clean-review-head Linux diagnostics:
application 243/243 (three separate scale entries ignored, 4.803 s), Python 238
total (237 passed/one Windows junction skip, 14.970 s), strict application
Clippy (7.51 s), three actual external E0603 boundaries, three release binaries,
self-test and real child-fault recovery. Run 36823756631 passed both macOS
subjects and Linux storage; both Windows subjects failed their registrar
fixture because PowerShell marshaled `System.RuntimeType` as an object.
Its exact receipts and terminal status are retained in
[20261001-703e9-verification.json](../../../docs/modules/ui.native/history/20261001-703e9-verification.json). The subsequent independent Darwin ACL/FIFO
review and Windows failure require this new freeze.

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

Real macOS ACL fixtures require unchanged 0700/0600 modes and compare original
bytes and ACLs. Fixture-only ACL removal establishes a control solely on newly
created owned temporary directories; production never removes an ACL. Source
presence and Linux execution do not qualify Darwin behavior. An ownership-ignored
volume still requires a real target-host mount receipt; no static bit assertion
or current ACL fixture is presented as that receipt. A trusted owner may change
permissions after validation; these checks do not provide filesystem transactions
or independent authorization.

Historical EBD source `ebd04a7ed458aa5feaba69525f48f3623c4db033` repaired checkout
bytes, cfg/FIFO, fixture PATH and Windows registrar ABI. Its Linux debug
application 243/243 (5.581 s, three scale entries ignored), Python 238 total
(237 passed/one Windows junction skip, 20.778 s), map 104/104 (22.123 s),
package/portal 36/36 (0.167 s), projection seven tests, strict application Clippy
(150 s) and full-symbol ACK 1/1 (3.020 s) are preserved in
[`20261001-ebd04-verification.json`](../../../docs/modules/ui.native/history/20261001-ebd04-verification.json).
Run 36822033441 failed overall: identity, Linux head/merge (18 checks each,
including virtual GUI lifecycle) and storage (48 traces/all hard budgets)
succeeded; macOS full tests, Windows owner lint and aggregate failed. See its
[Linux child record](../../../docs/modules/ui.native/history/20261001-ebd04-linux-verification.json).
macOS full application tests failed copying absent `/bin/true`, and Windows
owner lint rejected five helper `unwrap` calls. These executable fixture defects
motivated 703e9bf and supersede the prior review stop. No historical subject
qualifies this new freeze.

Historical source `0c176c9d4df6055418529389bf0f749f74ac1a69` passed 243/243 normal
debug application tests in 6.377 s, with three separate scale entries ignored,
and strict debug all-target/all-feature application Clippy in 9.39 s. The
full-symbol ACK fixture passed in 3.358 s. Python ran 236 tests successfully in
20.939 s: 235 passed and the Windows-only junction test skipped. Combined
native-adapter/global-map regressions passed 104/104 in 22.945 s, package/portal
passed 36/36 in 0.138 s, and projection generation/verification/lint plus seven
tests passed. Structural verification bound 404 Git blobs, 30 selection paths
and 16 local Cargo dependencies to that historical source. The source-specific
local results and run 36820183453 are preserved in
[`20261001-0c176-verification.json`](../../../docs/modules/ui.native/history/20261001-0c176-verification.json).
That run passed Linux head/merge and storage with 48 traces/all hard budgets,
but failed macOS strict
compilation and one Windows Python command fixture.

Historical 32310 evidence is preserved in
[`20261001-32310-verification.json`](../../../docs/modules/ui.native/history/20261001-32310-verification.json).
Its 243 release/227 Python/86 adapter counts and release scale measurements
belong to that source. The later run 36796737020 failed overall despite a
successful 18-check Linux merge subject and storage hard-budget validation with
48 traces; Linux head ACK and macOS/Windows Python failed. Those executed
failures supersede the prior queued/no-new-findings statements. Successful old
subjects, including owner 210 and virtual Xvfb desktop evidence, do not qualify
the new freeze or replace physical-host acceptance. The candidate remains
incomplete, with an explicit non-Linux Open/Reveal capability gap.

Source coverage, sustained soak, all storage ceilings, physical Windows/macOS/
X11/Wayland behavior, IME, mixed DPI, screen readers, keyboard navigation,
production key custody, signing/notarization, independent supply-chain acceptance
and promotion review remain explicit gates. Local tests cannot close these gates.
`productionQualified`, `deploymentQualified` and `releaseAuthorized` remain false.
