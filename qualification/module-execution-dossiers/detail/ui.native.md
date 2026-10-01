# ui.native: implementation and qualification dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-qualified-integration-20260928`.
Audit revision: `work/ui-native-adversarial-audit-20261001`.
Immutable implementation source: `703e9bf2871b26d646f1c4d748e0b0061f70ad3c`.
Implementation tree: `d549e3e492093810b685c7d65d58d6983566a82b`.
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

Current source 703e9bf repairs three fixture files after real EBD CI failures:
the actual Unix zero-exit candidate copy and environment-only picker Command use
`/usr/bin/true`, while Windows authority helper errors propagate via Result.
Strict lints, startup denial, rollback digest/0751 mode, owner lifetime and all
production flows remain intact. The source selection remains 406 Git blobs,
32 paths and 16 local Cargo dependencies, inventory SHA256
`485b4790cdbb806fc51653d280ff4f7b690bff35e95ba4301ce653fd339f7091`.
The re-anchored precommit structural checker passed for this exact 406/32/16
inventory. This is a structural diagnostic, not platform or release acceptance.
CURRENT_SOURCE.json binds this new inventory. Current complete suites, strict
lint, owner, full-symbol ACK,
release, storage/performance and same-run CI are pending.

The Linux focused 2/2 pass (0.163 s) ran on the post-EBD worktree with all three
repaired files matching 703e9bf Git blobs. It is not a full current-source suite
or macOS/Windows pass. The standalone same-shape Rust 1.95 Clippy probe exited 0,
with type complexity 230 below 250; it does not compile the Windows fixture.

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
